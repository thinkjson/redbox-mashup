import webapp2
import jinja2
import os
import json
import logging
import urllib
import math
from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api.urlfetch import fetch
from settings import REDBOX_APIKEY, RT_APIKEY
from lxml import etree
from google.appengine.ext import ndb
from levenshtein import levenshtein
from datetime import date

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))


class Movie(ndb.Expando):
    _default_indexed = False


def get_movie(movie_id):
    # Check if ndb has the movie, and if so return it
    movie = Movie.get_by_id(movie_id)
    if movie is not None:
        return movie

    # If not create a model and populate it from the Redbox API
    movie = Movie(id=movie_id)
    content = memcache.get("movie-%s" % movie_id)
    if content is None:
        url = "https://api.redbox.com/v3/products/%s?apiKey=%s" % (movie_id, REDBOX_APIKEY)
        response = fetch(url)
        if response.status_code != 200:
            raise ValueError("Could not retrieve Redbox information for id: %s" % movie_id)
        else:
            content = response.content
            memcache.set("movie-%s" % movie_id, content)

    movie_root = etree.fromstring(content)
    movie_data = movie_root.iterchildren().next()
    movie.populate(**movie_data.attrib)

    attributes = {}
    for el in movie_data.iterchildren():
        tag = el.tag.split('}')[1] if '}' in el.tag else el.tag
        attributes[tag.lower()] = el.text
    movie.populate(**attributes)
    year_offset = int(math.pow(math.log( \
        date.today().year - (date.today().year-x) \
        ), 2))

    # Then look up Rotten Tomatoes scores
    content = memcache.get("rotten-tomatoes-%s" % movie.title)
    if content is None:
        url = "http://api.rottentomatoes.com/api/public/v1.0/movies.json?q=%s&apikey=%s"\
            % (urllib.quote(movie.title), RT_APIKEY)
        response = fetch(url)
        if response.status_code != 200:
            raise ValueError("Could not retrieve Rotten Tomatoes information for %s: %s" % (movie.title, url))
        else:
            content = response.content
            memcache.set("rotten-tomatoes-%s" % movie.title, response.content)
    for result in json.loads(content)['movies']:
        if not hasattr(movie, 'score') and \
                levenshtein(movie.title, result['title'])/len(movie.title) < 0.2:
            # This is where the magic happens
            movie.score = (((result['ratings']['critics_score'] * 2) +
                result['ratings']['audience_score']) / 3) -
                year_offset
    if not hasattr(movie, 'score'):
        movie.score = 0

    # Save and return movie
    movie.put()
    return movie


def look_up_movies(zipcode):
    # Fetch inventory for all kiosks within 10 miles
    results = []
    url = "https://api.redbox.com/stores/postalcode/%s?apiKey=%s"\
        % (zipcode, REDBOX_APIKEY)
    response = fetch(url)
    if response.status_code != 200:
            raise ValueError("Could not retrieve kiosks near %s" % zipcode)
    kiosks_root = etree.fromstring(response.content)
    kiosks = kiosks_root.iterchildren()
    num_kiosks = 0
    for kiosk in kiosks:
        num_kiosks += 1
        if num_kiosks > 5:
            continue
        store_id = kiosk.attrib['storeId']
        logging.info("Looking up inventory for store %s" % store_id)
        url = "https://api.redbox.com/v3/inventory/stores/%s?apiKey=%s"\
            % (store_id, REDBOX_APIKEY)
        response = fetch(url)
        if response.status_code != 200:
            raise ValueError("Could not retrieve inventory for store: %s" % store_id)
        inventory_root = etree.fromstring(response.content)
        for inventory in inventory_root.iterchildren().next().iterchildren():
            if inventory.attrib['inventoryStatus'] != "InStock":
                continue
            movie_id = inventory.attrib['productId']
            movie = get_movie(movie_id)
            distance = float(kiosk\
                .find('{http://api.redbox.com/Stores/v2}DistanceFromSearchLocation')\
                .text)
            results.append({
                "score": movie.score,
                "title": movie.title,
                "distance": distance
            })

    # Look up scores for each title
    # Sort list by score, then by title, then by distance
    # Generate a unique list of titles
    # Truncate at top 10
    # Generate reservation links
    #   http://www.redbox.com/externalcart?titleID={product_id}&StoreGUID={store_id}

    # Persist list to memcache
    memcache.set("movies-%s" % zipcode, results)
    return results


class MainHandler(webapp2.RequestHandler):
    def get(self):
        template_values = {}
        template = jinja_environment.get_template('templates/index.html')

        self.response.out.write(template.render(template_values))


class ZIPHandler(webapp2.RequestHandler):
    def get(self, zipcode):
        # TODO - check if zipcode is valid and convert to int
        #results = memcache.get("movies-%s" % zipcode)
        #if results is None:
        results = look_up_movies(zipcode)

        # TODO - return 'in progress' template
        self.response.write(json.dumps(results))

app = webapp2.WSGIApplication([
    ('/', MainHandler),
    (r'/(\d+)', ZIPHandler),
])
