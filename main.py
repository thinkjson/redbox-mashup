import webapp2
import jinja2
import os
import json
import logging
import urllib
import math
from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from settings import REDBOX_APIKEY, RT_APIKEY
from lxml import etree
from google.appengine.ext import ndb
from levenshtein import levenshtein
from datetime import date
import re
import copy
import time
import unicodedata
from operator import itemgetter
from hashlib import md5
from datetime import datetime
from webapp2_extras.appengine.users import admin_required

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))


class Movie(ndb.Expando):
    _default_indexed = False


class Response():
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content


# Cache all API calls for an hour
def fetch(url, **kwargs):
    response = memcache.get(md5(url).hexdigest())
    if response is None:
        api_response = urlfetch.fetch(url, **kwargs)
        response = Response(api_response.status_code, api_response.content)
        memcache.set(md5(url).hexdigest(), response, time=3600)
    return response


def download_movies(page):
    url = "https://api.redbox.com/v3/products/movies?pageSize=10&pageNum=%s&apiKey=%s"\
        % (page, REDBOX_APIKEY)
    logging.info("Fetching products...")
    try:
        response = fetch(url, headers={'Accept': 'application/json'})
        logging.info("complete!")
        movies = json.loads(response.content)
    except:
        movies = {}
    if 'Products' not in movies or \
            'Movie' not in movies['Products'] or \
            len(movies['Products']['Movie']) == 0:
        logging.info("Download complete!")
        return
    for obj in movies['Products']['Movie']:
        time.sleep(1)
        movie_id = obj['@productId']
        movie = Movie.get_by_id(movie_id)
        if movie is None:
            movie = Movie(id=movie_id)
        properties = {}
        for key in obj:
            if type(obj[key]) != dict:
                properties[key.replace('@','').lower()] = obj[key]
        movie.populate(**properties)
        if type(movie.title) != str and type(movie.title) != unicode:
            movie.title = unicode(movie.title)
        if 'RatingContext' in obj and \
                '@ratingReason' in obj['RatingContext']:
            movie.ratingReason = obj['RatingContext']['@ratingReason']
        if 'Actors' in obj and 'Person' in obj['Actors']:
            movie.actors = ", ".join(obj['Actors']['Person'])
        if 'BoxArtImages' in obj and 'link' in obj['BoxArtImages'] \
                and type(obj['BoxArtImages']['link']) == list \
                and len(obj['BoxArtImages']['link']) >= 3 \
                and '@href' in obj['BoxArtImages']['link'][2]:
            movie.thumb = obj['BoxArtImages']['link'][2]['@href']
        movie.put()

        # Don't recalc score if it's really bad
        if hasattr(movie, 'score') and movie.score < 40 and movie.score > 0:
            continue
        movie.score = -1

        # Then look up Rotten Tomatoes scores
        url = "http://www.omdbapi.com/?t=%s&tomatoes=true"\
            % (urllib.quote(unicodedata.normalize('NFKD', movie.title).encode('ascii', 'ignore')))
        if hasattr(movie, 'releaseyear'):
            url += "&y=%s" % (movie.releaseyear)
        response = fetch(url)
        
        if response.status_code != 200:
            logging.error("Could not retrieve Rotten Tomatoes information for %s: %s" % (obj['Title'], url))
            continue
        else:
            result = json.loads(response.content)
            if 'Response' in result and result['Response'] == 'False':
                continue

        # This is where the magic happens
        logging.info("Recalculating score for %s" % obj['Title'])
        movie.thumb = result['Poster'] if 'Poster' in result else ''
        try:
            movie.critics_score = int(result['tomatoMeter']) if 'tomatoMeter' in result else 0
        except:
            movie.critics_score = 0
        try:
            movie.critics_consensus = result['tomatoConsensus'] if 'tomatoConsensus' in result else ''
        except:
            movie.critics_consensus = ''
        try:
            movie.audience_score = int(result['tomatoUserMeter']) if 'tomatoUserMeter' in result else 0
        except:
            movie.audience_score = 0
        movie.score = movie.audience_score

        if 'Released' in result:
            try:
                movie.releasedate = datetime.strptime(result['Released'], "%d %b %Y")
            except:
                movie.releasedate = None

        # Adjust score based on release date
        try:
            daysago = (datetime.now() - movie.releasedate).days
        except:
            daysago = 90
        movie.daysago = daysago
        if daysago <= 30:
            movie.score += 5
        if daysago <= 7:
            movie.score += 10
        if daysago > 90:
            movie.score -= 20
        if not hasattr(movie, 'score'):
            movie.score = 0

        # Save and return movie
        movie.put()


def fetch_inventory(zipcode):
    # Fetch inventory for all kiosks within 10 miles
    results = []
    logging.info("Fetching kiosks near %s" % zipcode)
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
        if num_kiosks > 7:
            continue
        store_id = kiosk.attrib['storeId']
        logging.info("Looking up inventory for store %s" % store_id)
        url = "https://api.redbox.com/v3/inventory/stores/%s?apiKey=%s"\
            % (store_id, REDBOX_APIKEY)
        response = fetch(url)
        if response.status_code != 200:
            logging.error("Could not retrieve inventory for store: %s" % store_id)
            continue
        inventory_root = etree.fromstring(response.content)
        for inventory in inventory_root.iterchildren().next().iterchildren():
            if inventory.attrib['inventoryStatus'] != "InStock":
                continue
            movie_id = inventory.attrib['productId']
            movie = Movie.get_by_id(movie_id)
            if movie is None:
                # TODO - queue creation
                continue
            if not hasattr(movie, 'score') or not hasattr(movie, 'critics_consensus'):
                movie.key.delete()
                continue
            distance = float(kiosk\
                .find('{http://api.redbox.com/Stores/v2}DistanceFromSearchLocation')\
                .text)
            output = movie.to_dict()
            output['distance'] = distance
            output['reservation_link'] = "http://www.redbox.com/externalcart?titleID=%s&StoreGUID=%s" % (movie_id.lower(), store_id.lower())
            results.append(output)

    # Generate a unique list of titles, saving closest
    results_keys = {}
    for result in results:
        if result['title'] not in results_keys or \
                results_keys[result['title']]['distance'] > result['distance']:
            results_keys[result['title']] = result
    unique_results = []
    for result in results_keys:
        unique_results.append(results_keys[result])

    # Sort list by score, truncate list
    unique_results = sorted(unique_results, key=itemgetter('score'), reverse=True)[:50]

    # Persist list to memcache
    memcache.set("zipcode-%s" % zipcode, unique_results, time=3600)
    memcache.set("zipcode-%s-backup" % zipcode, unique_results)
    return unique_results


class MainHandler(webapp2.RequestHandler):
    def get(self):
        # If zip code entered, without javascript working,
        # we'll receive the zip code here. Let's handle that
        # and redirect to the proper place:
        zip_code = self.request.GET.get('zip')
        if zip_code and re.match(r'^\d{5}$', zip_code):
            # TODO: Default 302 okay? Otherwise, set 'permanent=True'.
            # TODO: URL/Route duplication. Need to use named route:
            return self.redirect('/{zip_code}'.format(zip_code=zip_code))
        template_values = {}
        if self.request.get('loading') != '':
            template = jinja_environment.get_template('templates/loading.html')
        else:
            template = jinja_environment.get_template('templates/index.html')
            self.response.headers['Cache-Control'] = 'public, max-age=3600'
        self.response.out.write(template.render(template_values))


class ZIPHandler(webapp2.RequestHandler):
    def get(self, zipcode):
        results = memcache.get("zipcode-%s" % zipcode)
        if results is None or results == "loading":
            backup_results = memcache.get("zipcode-%s-backup" % zipcode)
            if results != "loading":
                memcache.set("zipcode-%s" % zipcode, "loading", time=3600)
                deferred.defer(fetch_inventory, zipcode)
            if backup_results is None:
                template = jinja_environment.get_template(
                    'templates/loading.html')
                self.response.out.write(template.render({}))
                return
            else:
                results = backup_results

        template_values = {"results": results,
                           "zipcode": zipcode}
        template = jinja_environment.get_template('templates/zipcode.html')
        self.response.out.write(template.render(template_values))
        self.response.headers['Cache-Control'] = 'public, max-age=3600'


class MoviesHandler(webapp2.RequestHandler):
    def get(self):
        for page in range(50):
            deferred.defer(download_movies, page, _target='movies')
        logging.info("Inventory download queued")
        self.abort(404)


app = webapp2.WSGIApplication([
    ('/', MainHandler),
    (r'/(\d{5})', ZIPHandler),
    ('/movies/', MoviesHandler)
])
