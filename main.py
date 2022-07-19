import argparse
from datetime import datetime, timedelta
import logging
import sys

import requests
import twitter

from secrets import twitter_credentials

LOGGING_FORMAT = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
# LAX and ELP are good for testing
LOCATIONS = [
    # ('LAX', 5180)
    # ('ELP', 5005)
    ('PIA', 11002),
    ('STL', 12021)
]

HOME_ZIP = 63021
MAX_DISTANCE_MILES = 250
DELTA = 26  # Weeks

SCHEDULER_API_URL = 'https://ttp.cbp.dhs.gov/schedulerapi/locations/{location}/slots?startTimestamp={start}&endTimestamp={end}'
LOCATION_LIST_API_URL = 'https://ttp.cbp.dhs.gov/schedulerapi/locations/?inviteOnly=false&operational=true&serviceName=Global%20Entry'
ZIP_CODE_DIST_API_URL = 'https://zipcodedistance.herokuapp.com/api/getDistance/zipcode?zipcode1={zip1}&zipcode2={zip2}&unit=M'
TTP_TIME_FORMAT = '%Y-%m-%dT%H:%M'

NOTIF_MESSAGE = 'New appointment slot open at {location}: {date}'
MESSAGE_TIME_FORMAT = '%A, %B %d, %Y at %I:%M %p'

def tweet(message):
    api = twitter.Api(**twitter_credentials)
    try:
        api.PostUpdate(message)
        logging.info('Tweet Posted')
    except twitter.TwitterError as e:
        if len(e.message) == 1 and e.message[0]['code'] == 187:
            logging.info('Tweet rejected (duplicate status)')
        else:
            raise

def calculate_distance(home_zip, location_zip, max_distance):
    url = ZIP_CODE_DIST_API_URL.format(zip1=home_zip, zip2=location_zip)
    try:
        results = requests.get(url).json()
    except requests.ConnectionError:
        logging.exception('Could not connect to distance API')
        sys.exit(1)
    if 'distance' in results:
        distance = results['distance']
        if distance < max_distance:
            return distance
    else:
        # Several zipcodes aren't found
        logging.debug('ZipCode %s not found', location_zip)
        logging.debug(results)
    return False

def get_full_location_list():
    url = LOCATION_LIST_API_URL
    locations = []
    try:
        results = requests.get(url).json()
    except requests.ConnectionError:
        logging.exception('Could not connect to scheduler API')
        sys.exit(1)
    for result in results:
        if result['countryCode'] == 'US':
            name = result['shortName']
            if not name:
                name = result['name']
            location_id = result['id']
            zipcode = result['postalCode'][:5]
            logging.debug('Found %s in %s', name, zipcode)
            locations.append((location_id, name, zipcode))
        else:
            logging.debug('Outside the US')
    return locations

def is_location_nearby(name, zipcode):
    distance = calculate_distance(HOME_ZIP, zipcode, MAX_DISTANCE_MILES)
    if distance:
        logging.info('*Nearby airport %s is in %s. %f miles away', name, zipcode, distance)

def check_for_openings(location_name, location_code, test_mode=True):
    start = datetime.now()
    end = start + timedelta(weeks=DELTA)

    url = SCHEDULER_API_URL.format(location=location_code,
                                   start=start.strftime(TTP_TIME_FORMAT),
                                   end=end.strftime(TTP_TIME_FORMAT))
    try:
        results = requests.get(url).json()  # List of flat appointment objects
    except requests.ConnectionError:
        logging.exception('Could not connect to scheduler API')
        sys.exit(1)

    for result in results:
        if result['active'] > 0:
            logging.info('Opening found for {}'.format(location_name))

            timestamp = datetime.strptime(result['timestamp'], TTP_TIME_FORMAT)
            message = NOTIF_MESSAGE.format(location=location_name,
                                           date=timestamp.strftime(MESSAGE_TIME_FORMAT))
            if test_mode:
                print(message)
            else:
                logging.info('Tweeting: ' + message)
                tweet(message)
            return  # Halt on first match

    logging.info('No openings for {}'.format(location_name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', '-t', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(format=LOGGING_FORMAT,
                            level=logging.INFO,
                            stream=sys.stdout)
    logging.info('Checking main locations')
    for location_name, location_code in LOCATIONS:
        check_for_openings(location_name, location_code, args.test)

    logging.info('Find locations within %d miles of %d', MAX_DISTANCE_MILES, HOME_ZIP)
    locations = get_full_location_list()
    logging.info('Found %d locations', len(locations))
    for (location_id, name, zipcode) in locations:
        if is_location_nearby(name, zipcode):
            check_for_openings(location_name, location_id, args.test)

if __name__ == '__main__':
    main()
