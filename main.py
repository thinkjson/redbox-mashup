import webapp2
from google.appengine.ext import deferred
from google.appengine.api import memcache
from google.appengine.api.urlfetch import fetch
from settings import APIKEY

# Get locations near a zip code


def look_up_movies(zipcode):
    # Fetch kiosks within 10 miles
    response = fetch("https://api.redbox.com/stores/postalcode/%d?apiKey=%s" % (zipcode, APIKEY))
    
    # Fetch inventory for each kiosk
    # Look up scores for each title
    # Sort list by score, then by title, then by distance
    # Generate a unique list of titles
    # Truncate at top 10
    # Persist list to memcache


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
