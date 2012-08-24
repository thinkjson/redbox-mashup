import webapp2
import jinja2
import os
from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api.urlfetch import fetch
from settings import REDBOX_APIKEY, RT_APIKEY
from lxml import etree
from google.appengine.ext import ndb
from levenshtein import levenshtein

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))


class Movie(ndb.Expando):
    pass


def get_movie(movie_id):
    # Check if ndb has the movie, and if so return it
    movie = Movie.get_by_id(movie_id)
    if movie is not None:
        return movie

    # If not create a model and populate it from the Redbox API
    movie = Movie()
    url = "https://api.redbox.com/products/%s?apiKey=%s" % (movie_id, APIKEY)
    response = fetch(url)
    if response.status != 200:
        raise ValueError("Could not retrieve Redbox information for id: %s" % movie_id)
    movie_root = etree.fromstring(response.content)
    movie_data = movie_root.iterchildren().next()
    movie.set(movie_data.attrib)

    attributes = {}
    for el in movie_data.iterchildren():
        tag = el.tag.split('}')[1] if '}' in el.tag else el.tag
        attributes[tag.lower()] = el.text
    movie.set(attributes)

    # Then look up Rotten Tomatoes scores
    url = "http://api.rottentomatoes.com/api/public/v1.0/movies.json?q=%s&apikey=%s"\
        % (movie.title, RT_APIKEY)
    response = fetch(url)
    if response.status != 200:
        raise ValueError("Could not retrieve Rotten Tomatoes information for id: %s" % movie_id)
    for result in json.loads(response.content)['movies']:
        if movie.score is None and \
                levenshtein(movie.title, result['title'])/len(movie.title) < 0.2:
            movie.score = ((result['ratings']['critics_score'] * 2) +
                result['ratings']['audience_score']) / 3

    # Save and return movie
    movie.put()
    return movie


def look_up_movies(zipcode):
    # Fetch inventory for all kiosks within 10 miles
    results = []
    url = "https://api.redbox.com/stores/postalcode/%s?apiKey=%s"\
        % (zipcode, REDBOX_APIKEY)
    response = fetch(url)
    kiosks_root = etree.fromstring(response.content)
    kiosks = kiosks_root.iterchildren()
    for kiosk in kiosks:
        store_id = kiosk.attrib['storeId']
        url = "https://api.redbox.com/inventory/stores/%s?apiKey=%s"\
            % (store_id, REDBOX_APIKEY)
        response = fetch(url)
        inventory_root = etree.fromstring(response.content)
        for inventory in inventory_root.iterchildren().next().iterchildren():
            if inventory.attrib['inventoryStatus'] != "InStock":
                continue
            movie_id = inventory['productId']
            movie = get_movie(movie_id)
            results.append({
                "score": movie.score,
                "title": movie.title,
                "distance": kiosk.distance
            })

    # Look up scores for each title
    # Sort list by score, then by title, then by distance
    # Generate a unique list of titles
    # Truncate at top 10
    # Generate reservation links
    #   http://www.redbox.com/externalcart?titleID={product_id}&StoreGUID={store_id}
    # Persist list to memcache
    return


class MainHandler(webapp2.RequestHandler):
    def get(self):
        template_values = {}
        template = jinja_environment.get_template('templates/index.html')

        self.response.out.write(template.render(template_values))


class ZIPHandler(webapp2.RequestHandler):
    def get(self, zipcode):
        movies = memcache.get("movies-%d" % zipcode)
        if movies is not None:
            # return template rendered with movies
            pass
        else:
            # Fire off deferred job
            deferred.defer(look_up_movies, zipcode)

            # return 'in progress' template
            pass

app = webapp2.WSGIApplication([
    ('/', MainHandler),
    (r'/(\d+)', ZIPHandler),
])
