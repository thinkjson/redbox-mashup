import webapp2
from google.appengine.ext import deferred
from google.appengine.api import memcache
from settings import APIKEY

# Get locations near a zip code


def look_up_movies(zip):
    # Do everything necessary to generate top 10 list
    "https://api.redbox.com/stores/postalcode/73034?apiKey=%s" % APIKEY
    return


class MainHandler(webapp2.RequestHandler):
    def get(self):
        self.request.write("Prompt for a zip code")


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
