import webapp2
import jinja2
import os
from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api.urlfetch import fetch
from settings import APIKEY
from lxml import etree
from google.appengine.ext import ndb

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

# Get locations near a zip code

class Movie(ndb.Expando):
    pass


def get_movie(movie_id):
    # Check if ndb has the movie
    movie = Movie.get_by_id(movie_id)
    if movie is not None:
        return movie

    # If not create a model and populate it from the Redbox API
    # Then look up Rotten Tomatoes scores
    pass


def look_up_movies(zipcode):
    # Fetch inventory for all kiosks within 10 miles
    results = []
    url = "https://api.redbox.com/stores/postalcode/%s?apiKey=%s"\
        % (zipcode, APIKEY)
    response = fetch(url)
    kiosks_root = etree.fromstring(response.content)
    kiosks = kiosks_root.iterchildren()
    for kiosk in kiosks:
        store_id = kiosk.attrib['storeId']
        url = "https://api.redbox.com/stores/inventory/%s?apiKey=%s"\
            % (store_id, APIKEY)
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
