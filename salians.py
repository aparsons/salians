import argparse
import logging
import requests
import time


class SaliansError(Exception):
    pass


class NoResponseError(SaliansError):
    pass


class PlayerInfo:
    def __init__(self, active_planet, level, score, next_level_score):
        self.active_planet = active_planet
        self.level = level
        self.score = score
        self.next_level_score = next_level_score

    def __str__(self):
        return 'Level {0}, Score {1}, Next Level Score {2}, Completion {3}'.format(self.level, self.score, self.next_level_score, self.completion())

    @staticmethod
    def from_json(json):
        active_planet = -1
        if 'active_planet' in json:
            active_planet = int(json['active_planet'])
        return PlayerInfo(active_planet, int(json['level']), int(json['score']), int(json['next_level_score']))

    def completion(self):
        return '{0:.2f}%'.format((self.score / self.next_level_score) * 100.0)


class PlanetSummary:
    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __str__(self):
        return '{0} (#{1})'.format(self.name, self.id)

    @staticmethod
    def from_json(json):
        return PlanetSummary(int(json['id']), json['state']['name'])


class Zone:
    def __init__(self, zone_position, type, difficulty, captured, capture_progress):
        self.zone_position = zone_position
        self.type = type
        self.difficulty = difficulty
        self.captured = captured
        self.capture_progress = capture_progress

    def __str__(self):
        if self.captured:
            return 'Zone #{0}, {1}: {2}'.format(self.zone_position, self.get_difficulty_string(),
                                                      self.get_captured_string(), self.get_capture_progress_string())
        else:
            return 'Zone #{0}, {1}: {2} ({3})'.format(self.zone_position, self.get_difficulty_string(), self.get_captured_string(), self.get_capture_progress_string())

    def get_difficulty_string(self):
        return {
            1: 'Low',
            2: 'Medium',
            3: 'High',
            4: 'Boss'
        }.get(self.difficulty)

    def get_captured_string(self):
        return {
            True: 'Captured',
            False: 'Uncaptured'
        }.get(self.captured)

    def get_capture_progress_string(self):
        if self.captured:
            return '100%'
        else:
            return '{0:.0f}%'.format(self.capture_progress * 100.00)

    def get_difficulty_score(self):
        return {
            1: 120 * 5,
            2: 120 * 10,
            3: 120 * 20,
            4: 120 * 40
        }.get(self.difficulty)

    @staticmethod
    def from_json(json):
        return Zone(json['zone_position'], json['type'], json['difficulty'], json['captured'],  json['capture_progress'])


class PlanetDetails:
    def __init__(self, id, name, zones):
        self.id = id
        self.name = name
        self.zones = zones

    def __str__(self):
        return '{0} (#{1})'.format(self.name, self.id)

    @staticmethod
    def from_json(json):
        zones = []
        for zone_json in json['zones']:
            zones.append(Zone.from_json(zone_json))

        return PlanetDetails(int(json['id']), json['state']['name'], zones)


class PlanetZoneTuple:
    def __init__(self, planet_details, zone):
        self.planet_details = planet_details
        self.zone = zone

    def __str__(self):
        return '{0}, {1} weight={2:.5f}'.format(self.planet_details, self.zone, self.weight())

    def weight(self):
        difficulty = {1: 2, 2: 4, 3: 8, 4: 100}.get(self.zone.difficulty)
        if self.zone.captured:
            return 0
        elif self.zone.difficulty is 3 and self.zone.capture_progress >= 0.95:
            return 0
        elif self.zone.difficulty is 2 and self.zone.capture_progress >= 0.96:
            return 0
        else:
            return difficulty * 8 + (1.0 - self.zone.capture_progress)


class Salians:
    version = '2.0'
    base_url = 'https://community.steam-api.com/ITerritoryControlMinigameService'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.87 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept': '*/*',
        'Origin': 'https://steamcommunity.com',
        'Referer': 'https://steamcommunity.com/saliengame/play'
    }

    def __init__(self, access_token, language='english'):
        self.logger = logging.getLogger('Salians')
        self.access_token = access_token
        self.language = language

    def run(self):
        self.logger.info("Starting Steam Salians Bot v" + self.version)
        while True:
            try:
                player_info = self._get_player_info()
                self.logger.info(player_info)

                active_planet = player_info.active_planet

                planet_zone = self._find_best_zone_position()
                if active_planet is not planet_zone.planet_details.id:
                    if active_planet is not -1:
                        self.logger.info('Leaving Planet...')
                        self._leave_planet(player_info.active_planet)
                    self.logger.info('Joining Planet... {0}'.format(planet_zone.planet_details))
                    self._join_planet(planet_zone.planet_details.id)

                # Join a Planet

                try:
                    self.logger.info('Joining Zone... {0}'.format(planet_zone))
                    self._join_zone(planet_zone.zone.zone_position)
                    self.logger.info('Joined!')
                except NoResponseError:
                    self.logger.info('Failed')

                self._sleep()

                # Report a Score
                retries = 0
                while retries < 6:
                    try:
                        self.logger.info('Reporting...')
                        self._report_score(planet_zone.zone.get_difficulty_score())
                        self.logger.info('Reported!')
                        break
                    except NoResponseError:
                        self.logger.info('Failed')
                    self._sleep(10, 1)
                    retries = retries + 1

                self.logger.info('Leaving Planet...')
                self._leave_planet(player_info.active_planet)
            except Exception as e:
                self.logger.warning('An unknown error occurred', e)
                self._sleep(60, 1)
                try:
                    player_info = self._get_player_info()
                    self._leave_planet(player_info.active_planet)
                except Exception as ee:
                    self.logger.warning('An unknown error occurred', ee)

    def _sleep(self, duration=20, times=6):
        for i in range(times):
            self.logger.info('Sleeping... {0}/{1}'.format(str((i + 1) * duration), str(duration * times)))
            time.sleep(duration)

    def _find_best_zone_position(self):
        def get_zones():
            zones = []
            planet_summaries = self._get_planet_summaries(1)
            for planet_summary in planet_summaries:
                planet_details = self._get_planet_details(planet_summary.id)
                for zone in planet_details.zones:
                    zones.append(PlanetZoneTuple(planet_details, zone))
            return zones
        zones = get_zones()

        from operator import methodcaller
        return sorted(zones, key=methodcaller('weight'))[-1]

    def _get_planet_summaries(self, active_only=0):
        url = '{0}/GetPlanets/v0001/?active_only={1}&language={2}'.format(self.base_url, active_only, self.language)
        json = requests.get(url=url, headers=self.headers).json()
        if json['response']:
            summaries = []
            for planet_json in json['response']['planets']:
                summaries.append(PlanetSummary.from_json(planet_json))
            return summaries
        else:
            raise NoResponseError

    def _get_planet_details(self, planet_id):
        url = '{0}/GetPlanet/v0001/?id={1}&language={2}'.format(self.base_url, planet_id, self.language)
        json = requests.get(url=url, headers=self.headers).json()
        if json['response']:
            return PlanetDetails.from_json(json['response']['planets'][0])
        else:
            raise NoResponseError

    def _get_player_info(self):
        url = '{0}/GetPlayerInfo/v0001/'.format(self.base_url)
        data = 'access_token={0}'.format(self.access_token)
        json = requests.post(url=url, data=data, headers=self.headers).json()
        if json['response']:
            return PlayerInfo.from_json(json['response'])
        else:
            raise NoResponseError

    def _leave_planet(self, planet_id):
        url = '{0}/LeaveGame/v0001/'.format(self.base_url)
        data = 'access_token={0}&gameid={1}'.format(self.access_token, planet_id)
        requests.post(url=url, data=data, headers=self.headers)

    def _join_planet(self, planet_id):
        url = '{0}/JoinPlanet/v0001/'.format(self.base_url)
        data = 'id={0}&access_token={1}'.format(planet_id, self.access_token)
        requests.post(url=url, data=data, headers=self.headers)

    def _join_zone(self, zone_position):
        url = '{0}/JoinZone/v0001/'.format(self.base_url)
        data = 'zone_position={0}&access_token={1}'.format(zone_position, self.access_token)
        json = requests.post(url=url, data=data, headers=self.headers).json()
        return json

    def _report_score(self, score):
        url = '{0}/ReportScore/v0001/'.format(self.base_url)
        data = 'access_token={0}&score={1}&language={2}'.format(self.access_token, score, self.language)
        json = requests.post(url=url, data=data, headers=self.headers).json()
        if json['response']:
            return True
        else:
            raise NoResponseError


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser("salians")
    parser.add_argument('access_token', help='Salians game access token value')
    args = parser.parse_args()

    Salians(access_token=args.access_token).run()
