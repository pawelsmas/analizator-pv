"""
European Cities Database for Geo Service
Major cities across Europe with coordinates and elevation.
Used as fallback when external geocoding APIs are unavailable.
"""

# Major European cities by country (ISO code)
# Format: city_name_lowercase -> {lat, lon, elev, name}
EUROPEAN_CITIES = {
    # Germany (DE)
    "DE": {
        "berlin": {"lat": 52.5200, "lon": 13.4050, "elev": 34, "name": "Berlin"},
        "hamburg": {"lat": 53.5511, "lon": 9.9937, "elev": 6, "name": "Hamburg"},
        "munich": {"lat": 48.1351, "lon": 11.5820, "elev": 520, "name": "München"},
        "münchen": {"lat": 48.1351, "lon": 11.5820, "elev": 520, "name": "München"},
        "monachium": {"lat": 48.1351, "lon": 11.5820, "elev": 520, "name": "München"},  # Polish
        "cologne": {"lat": 50.9375, "lon": 6.9603, "elev": 53, "name": "Köln"},
        "köln": {"lat": 50.9375, "lon": 6.9603, "elev": 53, "name": "Köln"},
        "koln": {"lat": 50.9375, "lon": 6.9603, "elev": 53, "name": "Köln"},
        "kolonia": {"lat": 50.9375, "lon": 6.9603, "elev": 53, "name": "Köln"},  # Polish
        "frankfurt": {"lat": 50.1109, "lon": 8.6821, "elev": 112, "name": "Frankfurt am Main"},
        "stuttgart": {"lat": 48.7758, "lon": 9.1829, "elev": 247, "name": "Stuttgart"},
        "düsseldorf": {"lat": 51.2277, "lon": 6.7735, "elev": 38, "name": "Düsseldorf"},
        "dusseldorf": {"lat": 51.2277, "lon": 6.7735, "elev": 38, "name": "Düsseldorf"},
        "dortmund": {"lat": 51.5136, "lon": 7.4653, "elev": 86, "name": "Dortmund"},
        "essen": {"lat": 51.4556, "lon": 7.0116, "elev": 116, "name": "Essen"},
        "leipzig": {"lat": 51.3397, "lon": 12.3731, "elev": 113, "name": "Leipzig"},
        "lipsk": {"lat": 51.3397, "lon": 12.3731, "elev": 113, "name": "Leipzig"},  # Polish
        "bremen": {"lat": 53.0793, "lon": 8.8017, "elev": 11, "name": "Bremen"},
        "brema": {"lat": 53.0793, "lon": 8.8017, "elev": 11, "name": "Bremen"},  # Polish
        "dresden": {"lat": 51.0504, "lon": 13.7373, "elev": 113, "name": "Dresden"},
        "drezno": {"lat": 51.0504, "lon": 13.7373, "elev": 113, "name": "Dresden"},  # Polish
        "hannover": {"lat": 52.3759, "lon": 9.7320, "elev": 55, "name": "Hannover"},
        "hanower": {"lat": 52.3759, "lon": 9.7320, "elev": 55, "name": "Hannover"},  # Polish
        "nürnberg": {"lat": 49.4521, "lon": 11.0767, "elev": 309, "name": "Nürnberg"},
        "nurnberg": {"lat": 49.4521, "lon": 11.0767, "elev": 309, "name": "Nürnberg"},
        "nuremberg": {"lat": 49.4521, "lon": 11.0767, "elev": 309, "name": "Nürnberg"},
        "norymberga": {"lat": 49.4521, "lon": 11.0767, "elev": 309, "name": "Nürnberg"},  # Polish
        "duisburg": {"lat": 51.4344, "lon": 6.7623, "elev": 31, "name": "Duisburg"},
        "bochum": {"lat": 51.4818, "lon": 7.2162, "elev": 100, "name": "Bochum"},
        "wuppertal": {"lat": 51.2562, "lon": 7.1508, "elev": 160, "name": "Wuppertal"},
        "bielefeld": {"lat": 52.0302, "lon": 8.5325, "elev": 118, "name": "Bielefeld"},
        "bonn": {"lat": 50.7374, "lon": 7.0982, "elev": 60, "name": "Bonn"},
        "mannheim": {"lat": 49.4875, "lon": 8.4660, "elev": 97, "name": "Mannheim"},
        "karlsruhe": {"lat": 49.0069, "lon": 8.4037, "elev": 115, "name": "Karlsruhe"},
        "augsburg": {"lat": 48.3705, "lon": 10.8978, "elev": 489, "name": "Augsburg"},
        "wiesbaden": {"lat": 50.0782, "lon": 8.2398, "elev": 115, "name": "Wiesbaden"},
        "aachen": {"lat": 50.7753, "lon": 6.0839, "elev": 173, "name": "Aachen"},
        "akwizgran": {"lat": 50.7753, "lon": 6.0839, "elev": 173, "name": "Aachen"},  # Polish
        "freiburg": {"lat": 47.9990, "lon": 7.8421, "elev": 278, "name": "Freiburg"},
    },

    # Czech Republic (CZ)
    "CZ": {
        "prague": {"lat": 50.0755, "lon": 14.4378, "elev": 235, "name": "Praha"},
        "praha": {"lat": 50.0755, "lon": 14.4378, "elev": 235, "name": "Praha"},
        "brno": {"lat": 49.1951, "lon": 16.6068, "elev": 237, "name": "Brno"},
        "ostrava": {"lat": 49.8209, "lon": 18.2625, "elev": 227, "name": "Ostrava"},
        "plzen": {"lat": 49.7384, "lon": 13.3736, "elev": 310, "name": "Plzeň"},
        "plzeň": {"lat": 49.7384, "lon": 13.3736, "elev": 310, "name": "Plzeň"},
        "liberec": {"lat": 50.7663, "lon": 15.0543, "elev": 374, "name": "Liberec"},
        "olomouc": {"lat": 49.5938, "lon": 17.2509, "elev": 219, "name": "Olomouc"},
        "ceske budejovice": {"lat": 48.9745, "lon": 14.4744, "elev": 381, "name": "České Budějovice"},
        "hradec kralove": {"lat": 50.2104, "lon": 15.8252, "elev": 235, "name": "Hradec Králové"},
        "pardubice": {"lat": 50.0343, "lon": 15.7812, "elev": 225, "name": "Pardubice"},
        "usti nad labem": {"lat": 50.6607, "lon": 14.0323, "elev": 140, "name": "Ústí nad Labem"},
        "zlin": {"lat": 49.2265, "lon": 17.6670, "elev": 230, "name": "Zlín"},
        "havirov": {"lat": 49.7797, "lon": 18.4370, "elev": 275, "name": "Havířov"},
        "kladno": {"lat": 50.1477, "lon": 14.1030, "elev": 380, "name": "Kladno"},
        "most": {"lat": 50.5030, "lon": 13.6364, "elev": 230, "name": "Most"},
        "opava": {"lat": 49.9388, "lon": 17.9026, "elev": 260, "name": "Opava"},
        "frydek-mistek": {"lat": 49.6879, "lon": 18.3538, "elev": 300, "name": "Frýdek-Místek"},
        "karvina": {"lat": 49.8541, "lon": 18.5429, "elev": 230, "name": "Karviná"},
        "jihlava": {"lat": 49.3961, "lon": 15.5912, "elev": 525, "name": "Jihlava"},
    },

    # Slovakia (SK)
    "SK": {
        "bratislava": {"lat": 48.1486, "lon": 17.1077, "elev": 134, "name": "Bratislava"},
        "kosice": {"lat": 48.7164, "lon": 21.2611, "elev": 206, "name": "Košice"},
        "košice": {"lat": 48.7164, "lon": 21.2611, "elev": 206, "name": "Košice"},
        "presov": {"lat": 48.9986, "lon": 21.2391, "elev": 255, "name": "Prešov"},
        "prešov": {"lat": 48.9986, "lon": 21.2391, "elev": 255, "name": "Prešov"},
        "zilina": {"lat": 49.2231, "lon": 18.7394, "elev": 342, "name": "Žilina"},
        "žilina": {"lat": 49.2231, "lon": 18.7394, "elev": 342, "name": "Žilina"},
        "banska bystrica": {"lat": 48.7360, "lon": 19.1461, "elev": 362, "name": "Banská Bystrica"},
        "nitra": {"lat": 48.3069, "lon": 18.0864, "elev": 167, "name": "Nitra"},
        "trnava": {"lat": 48.3774, "lon": 17.5883, "elev": 146, "name": "Trnava"},
        "martin": {"lat": 49.0636, "lon": 18.9214, "elev": 401, "name": "Martin"},
        "trencin": {"lat": 48.8945, "lon": 18.0441, "elev": 211, "name": "Trenčín"},
        "poprad": {"lat": 49.0513, "lon": 20.2976, "elev": 672, "name": "Poprad"},
    },

    # Austria (AT)
    "AT": {
        "vienna": {"lat": 48.2082, "lon": 16.3738, "elev": 171, "name": "Wien"},
        "wien": {"lat": 48.2082, "lon": 16.3738, "elev": 171, "name": "Wien"},
        "wieden": {"lat": 48.2082, "lon": 16.3738, "elev": 171, "name": "Wien"},  # Polish
        "wiedeń": {"lat": 48.2082, "lon": 16.3738, "elev": 171, "name": "Wien"},  # Polish
        "graz": {"lat": 47.0707, "lon": 15.4395, "elev": 353, "name": "Graz"},
        "linz": {"lat": 48.3069, "lon": 14.2858, "elev": 266, "name": "Linz"},
        "salzburg": {"lat": 47.8095, "lon": 13.0550, "elev": 424, "name": "Salzburg"},
        "innsbruck": {"lat": 47.2692, "lon": 11.4041, "elev": 574, "name": "Innsbruck"},
        "klagenfurt": {"lat": 46.6249, "lon": 14.3050, "elev": 446, "name": "Klagenfurt"},
        "villach": {"lat": 46.6111, "lon": 13.8558, "elev": 501, "name": "Villach"},
        "wels": {"lat": 48.1575, "lon": 14.0289, "elev": 317, "name": "Wels"},
        "st. polten": {"lat": 48.2047, "lon": 15.6256, "elev": 267, "name": "St. Pölten"},
        "st polten": {"lat": 48.2047, "lon": 15.6256, "elev": 267, "name": "St. Pölten"},
        "dornbirn": {"lat": 47.4125, "lon": 9.7417, "elev": 437, "name": "Dornbirn"},
        "steyr": {"lat": 48.0378, "lon": 14.4214, "elev": 310, "name": "Steyr"},
        "bregenz": {"lat": 47.5031, "lon": 9.7471, "elev": 398, "name": "Bregenz"},
    },

    # France (FR)
    "FR": {
        "paris": {"lat": 48.8566, "lon": 2.3522, "elev": 35, "name": "Paris"},
        "paryz": {"lat": 48.8566, "lon": 2.3522, "elev": 35, "name": "Paris"},  # Polish
        "paryż": {"lat": 48.8566, "lon": 2.3522, "elev": 35, "name": "Paris"},  # Polish
        "marseille": {"lat": 43.2965, "lon": 5.3698, "elev": 12, "name": "Marseille"},
        "marsylia": {"lat": 43.2965, "lon": 5.3698, "elev": 12, "name": "Marseille"},  # Polish
        "lyon": {"lat": 45.7640, "lon": 4.8357, "elev": 173, "name": "Lyon"},
        "toulouse": {"lat": 43.6047, "lon": 1.4442, "elev": 141, "name": "Toulouse"},
        "tuluza": {"lat": 43.6047, "lon": 1.4442, "elev": 141, "name": "Toulouse"},  # Polish
        "nice": {"lat": 43.7102, "lon": 7.2620, "elev": 10, "name": "Nice"},
        "nicea": {"lat": 43.7102, "lon": 7.2620, "elev": 10, "name": "Nice"},  # Polish
        "nantes": {"lat": 47.2184, "lon": -1.5536, "elev": 8, "name": "Nantes"},
        "strasbourg": {"lat": 48.5734, "lon": 7.7521, "elev": 142, "name": "Strasbourg"},
        "strasburg": {"lat": 48.5734, "lon": 7.7521, "elev": 142, "name": "Strasbourg"},  # Polish
        "montpellier": {"lat": 43.6108, "lon": 3.8767, "elev": 27, "name": "Montpellier"},
        "bordeaux": {"lat": 44.8378, "lon": -0.5792, "elev": 17, "name": "Bordeaux"},
        "bordeux": {"lat": 44.8378, "lon": -0.5792, "elev": 17, "name": "Bordeaux"},  # Common misspelling
        "lille": {"lat": 50.6292, "lon": 3.0573, "elev": 27, "name": "Lille"},
        "rennes": {"lat": 48.1173, "lon": -1.6778, "elev": 40, "name": "Rennes"},
        "reims": {"lat": 49.2583, "lon": 4.0317, "elev": 83, "name": "Reims"},
        "le havre": {"lat": 49.4944, "lon": 0.1079, "elev": 5, "name": "Le Havre"},
        "saint-etienne": {"lat": 45.4397, "lon": 4.3872, "elev": 484, "name": "Saint-Étienne"},
        "toulon": {"lat": 43.1242, "lon": 5.9280, "elev": 15, "name": "Toulon"},
        "grenoble": {"lat": 45.1885, "lon": 5.7245, "elev": 212, "name": "Grenoble"},
        "dijon": {"lat": 47.3220, "lon": 5.0415, "elev": 245, "name": "Dijon"},
        "angers": {"lat": 47.4784, "lon": -0.5632, "elev": 41, "name": "Angers"},
        "nancy": {"lat": 48.6921, "lon": 6.1844, "elev": 212, "name": "Nancy"},
        "metz": {"lat": 49.1193, "lon": 6.1757, "elev": 178, "name": "Metz"},
    },

    # Italy (IT)
    "IT": {
        "rome": {"lat": 41.9028, "lon": 12.4964, "elev": 21, "name": "Roma"},
        "roma": {"lat": 41.9028, "lon": 12.4964, "elev": 21, "name": "Roma"},
        "rzym": {"lat": 41.9028, "lon": 12.4964, "elev": 21, "name": "Roma"},  # Polish
        "milan": {"lat": 45.4642, "lon": 9.1900, "elev": 120, "name": "Milano"},
        "milano": {"lat": 45.4642, "lon": 9.1900, "elev": 120, "name": "Milano"},
        "mediolan": {"lat": 45.4642, "lon": 9.1900, "elev": 120, "name": "Milano"},  # Polish
        "naples": {"lat": 40.8518, "lon": 14.2681, "elev": 17, "name": "Napoli"},
        "napoli": {"lat": 40.8518, "lon": 14.2681, "elev": 17, "name": "Napoli"},
        "neapol": {"lat": 40.8518, "lon": 14.2681, "elev": 17, "name": "Napoli"},  # Polish
        "turin": {"lat": 45.0703, "lon": 7.6869, "elev": 239, "name": "Torino"},
        "torino": {"lat": 45.0703, "lon": 7.6869, "elev": 239, "name": "Torino"},
        "turyn": {"lat": 45.0703, "lon": 7.6869, "elev": 239, "name": "Torino"},  # Polish
        "palermo": {"lat": 38.1157, "lon": 13.3615, "elev": 14, "name": "Palermo"},
        "genoa": {"lat": 44.4056, "lon": 8.9463, "elev": 19, "name": "Genova"},
        "genova": {"lat": 44.4056, "lon": 8.9463, "elev": 19, "name": "Genova"},
        "genua": {"lat": 44.4056, "lon": 8.9463, "elev": 19, "name": "Genova"},  # Polish
        "bologna": {"lat": 44.4949, "lon": 11.3426, "elev": 54, "name": "Bologna"},
        "bolonia": {"lat": 44.4949, "lon": 11.3426, "elev": 54, "name": "Bologna"},  # Polish
        "florence": {"lat": 43.7696, "lon": 11.2558, "elev": 50, "name": "Firenze"},
        "firenze": {"lat": 43.7696, "lon": 11.2558, "elev": 50, "name": "Firenze"},
        "florencja": {"lat": 43.7696, "lon": 11.2558, "elev": 50, "name": "Firenze"},  # Polish
        "bari": {"lat": 41.1171, "lon": 16.8719, "elev": 5, "name": "Bari"},
        "catania": {"lat": 37.5079, "lon": 15.0830, "elev": 7, "name": "Catania"},
        "katania": {"lat": 37.5079, "lon": 15.0830, "elev": 7, "name": "Catania"},  # Polish
        "venice": {"lat": 45.4408, "lon": 12.3155, "elev": 1, "name": "Venezia"},
        "venezia": {"lat": 45.4408, "lon": 12.3155, "elev": 1, "name": "Venezia"},
        "wenecja": {"lat": 45.4408, "lon": 12.3155, "elev": 1, "name": "Venezia"},  # Polish
        "verona": {"lat": 45.4384, "lon": 10.9916, "elev": 59, "name": "Verona"},
        "werona": {"lat": 45.4384, "lon": 10.9916, "elev": 59, "name": "Verona"},  # Polish
        "messina": {"lat": 38.1938, "lon": 15.5540, "elev": 3, "name": "Messina"},
        "padova": {"lat": 45.4064, "lon": 11.8768, "elev": 12, "name": "Padova"},
        "padwa": {"lat": 45.4064, "lon": 11.8768, "elev": 12, "name": "Padova"},  # Polish
        "trieste": {"lat": 45.6495, "lon": 13.7768, "elev": 2, "name": "Trieste"},
        "triest": {"lat": 45.6495, "lon": 13.7768, "elev": 2, "name": "Trieste"},  # Polish
    },

    # Spain (ES)
    "ES": {
        "madrid": {"lat": 40.4168, "lon": -3.7038, "elev": 667, "name": "Madrid"},
        "barcelona": {"lat": 41.3851, "lon": 2.1734, "elev": 12, "name": "Barcelona"},
        "valencia": {"lat": 39.4699, "lon": -0.3763, "elev": 15, "name": "Valencia"},
        "seville": {"lat": 37.3891, "lon": -5.9845, "elev": 11, "name": "Sevilla"},
        "sevilla": {"lat": 37.3891, "lon": -5.9845, "elev": 11, "name": "Sevilla"},
        "zaragoza": {"lat": 41.6488, "lon": -0.8891, "elev": 199, "name": "Zaragoza"},
        "malaga": {"lat": 36.7213, "lon": -4.4214, "elev": 11, "name": "Málaga"},
        "málaga": {"lat": 36.7213, "lon": -4.4214, "elev": 11, "name": "Málaga"},
        "murcia": {"lat": 37.9922, "lon": -1.1307, "elev": 43, "name": "Murcia"},
        "palma": {"lat": 39.5696, "lon": 2.6502, "elev": 14, "name": "Palma de Mallorca"},
        "bilbao": {"lat": 43.2630, "lon": -2.9350, "elev": 19, "name": "Bilbao"},
        "alicante": {"lat": 38.3452, "lon": -0.4810, "elev": 12, "name": "Alicante"},
        "cordoba": {"lat": 37.8882, "lon": -4.7794, "elev": 123, "name": "Córdoba"},
        "córdoba": {"lat": 37.8882, "lon": -4.7794, "elev": 123, "name": "Córdoba"},
        "valladolid": {"lat": 41.6523, "lon": -4.7245, "elev": 698, "name": "Valladolid"},
        "vigo": {"lat": 42.2406, "lon": -8.7207, "elev": 15, "name": "Vigo"},
        "gijon": {"lat": 43.5453, "lon": -5.6635, "elev": 3, "name": "Gijón"},
        "granada": {"lat": 37.1773, "lon": -3.5986, "elev": 738, "name": "Granada"},
    },

    # Netherlands (NL)
    "NL": {
        "amsterdam": {"lat": 52.3676, "lon": 4.9041, "elev": -2, "name": "Amsterdam"},
        "rotterdam": {"lat": 51.9244, "lon": 4.4777, "elev": -1, "name": "Rotterdam"},
        "the hague": {"lat": 52.0705, "lon": 4.3007, "elev": 1, "name": "Den Haag"},
        "den haag": {"lat": 52.0705, "lon": 4.3007, "elev": 1, "name": "Den Haag"},
        "utrecht": {"lat": 52.0907, "lon": 5.1214, "elev": 5, "name": "Utrecht"},
        "eindhoven": {"lat": 51.4416, "lon": 5.4697, "elev": 18, "name": "Eindhoven"},
        "tilburg": {"lat": 51.5555, "lon": 5.0913, "elev": 14, "name": "Tilburg"},
        "groningen": {"lat": 53.2194, "lon": 6.5665, "elev": 3, "name": "Groningen"},
        "almere": {"lat": 52.3508, "lon": 5.2647, "elev": -3, "name": "Almere"},
        "breda": {"lat": 51.5719, "lon": 4.7683, "elev": 7, "name": "Breda"},
        "nijmegen": {"lat": 51.8126, "lon": 5.8372, "elev": 10, "name": "Nijmegen"},
        "arnhem": {"lat": 51.9851, "lon": 5.8987, "elev": 13, "name": "Arnhem"},
        "haarlem": {"lat": 52.3874, "lon": 4.6462, "elev": 1, "name": "Haarlem"},
        "enschede": {"lat": 52.2215, "lon": 6.8937, "elev": 34, "name": "Enschede"},
        "maastricht": {"lat": 50.8514, "lon": 5.6910, "elev": 50, "name": "Maastricht"},
    },

    # Belgium (BE)
    "BE": {
        "brussels": {"lat": 50.8503, "lon": 4.3517, "elev": 13, "name": "Bruxelles"},
        "bruxelles": {"lat": 50.8503, "lon": 4.3517, "elev": 13, "name": "Bruxelles"},
        "brussel": {"lat": 50.8503, "lon": 4.3517, "elev": 13, "name": "Bruxelles"},
        "bruksela": {"lat": 50.8503, "lon": 4.3517, "elev": 13, "name": "Bruxelles"},  # Polish
        "antwerp": {"lat": 51.2194, "lon": 4.4025, "elev": 7, "name": "Antwerpen"},
        "antwerpen": {"lat": 51.2194, "lon": 4.4025, "elev": 7, "name": "Antwerpen"},
        "antwerpia": {"lat": 51.2194, "lon": 4.4025, "elev": 7, "name": "Antwerpen"},  # Polish
        "ghent": {"lat": 51.0543, "lon": 3.7174, "elev": 5, "name": "Gent"},
        "gent": {"lat": 51.0543, "lon": 3.7174, "elev": 5, "name": "Gent"},
        "gandawa": {"lat": 51.0543, "lon": 3.7174, "elev": 5, "name": "Gent"},  # Polish
        "charleroi": {"lat": 50.4108, "lon": 4.4446, "elev": 141, "name": "Charleroi"},
        "liege": {"lat": 50.6326, "lon": 5.5797, "elev": 70, "name": "Liège"},
        "liège": {"lat": 50.6326, "lon": 5.5797, "elev": 70, "name": "Liège"},
        "brugia": {"lat": 51.2093, "lon": 3.2247, "elev": 7, "name": "Brugge"},  # Polish
        "bruges": {"lat": 51.2093, "lon": 3.2247, "elev": 7, "name": "Brugge"},
        "brugge": {"lat": 51.2093, "lon": 3.2247, "elev": 7, "name": "Brugge"},
        "namur": {"lat": 50.4674, "lon": 4.8720, "elev": 80, "name": "Namur"},
        "leuven": {"lat": 50.8798, "lon": 4.7005, "elev": 25, "name": "Leuven"},
        "mons": {"lat": 50.4542, "lon": 3.9567, "elev": 53, "name": "Mons"},
        "mechelen": {"lat": 51.0259, "lon": 4.4776, "elev": 8, "name": "Mechelen"},
    },

    # Switzerland (CH)
    "CH": {
        "zurich": {"lat": 47.3769, "lon": 8.5417, "elev": 408, "name": "Zürich"},
        "zürich": {"lat": 47.3769, "lon": 8.5417, "elev": 408, "name": "Zürich"},
        "geneva": {"lat": 46.2044, "lon": 6.1432, "elev": 375, "name": "Genève"},
        "geneve": {"lat": 46.2044, "lon": 6.1432, "elev": 375, "name": "Genève"},
        "genève": {"lat": 46.2044, "lon": 6.1432, "elev": 375, "name": "Genève"},
        "basel": {"lat": 47.5596, "lon": 7.5886, "elev": 260, "name": "Basel"},
        "bern": {"lat": 46.9480, "lon": 7.4474, "elev": 540, "name": "Bern"},
        "lausanne": {"lat": 46.5197, "lon": 6.6323, "elev": 495, "name": "Lausanne"},
        "winterthur": {"lat": 47.5006, "lon": 8.7240, "elev": 439, "name": "Winterthur"},
        "lucerne": {"lat": 47.0502, "lon": 8.3093, "elev": 436, "name": "Luzern"},
        "luzern": {"lat": 47.0502, "lon": 8.3093, "elev": 436, "name": "Luzern"},
        "st. gallen": {"lat": 47.4245, "lon": 9.3767, "elev": 675, "name": "St. Gallen"},
        "lugano": {"lat": 46.0037, "lon": 8.9511, "elev": 273, "name": "Lugano"},
        "biel": {"lat": 47.1368, "lon": 7.2467, "elev": 434, "name": "Biel/Bienne"},
    },

    # Hungary (HU)
    "HU": {
        "budapest": {"lat": 47.4979, "lon": 19.0402, "elev": 96, "name": "Budapest"},
        "debrecen": {"lat": 47.5316, "lon": 21.6273, "elev": 121, "name": "Debrecen"},
        "szeged": {"lat": 46.2530, "lon": 20.1414, "elev": 79, "name": "Szeged"},
        "miskolc": {"lat": 48.1035, "lon": 20.7784, "elev": 130, "name": "Miskolc"},
        "pecs": {"lat": 46.0727, "lon": 18.2323, "elev": 153, "name": "Pécs"},
        "pécs": {"lat": 46.0727, "lon": 18.2323, "elev": 153, "name": "Pécs"},
        "gyor": {"lat": 47.6875, "lon": 17.6504, "elev": 108, "name": "Győr"},
        "győr": {"lat": 47.6875, "lon": 17.6504, "elev": 108, "name": "Győr"},
        "nyiregyhaza": {"lat": 47.9553, "lon": 21.7177, "elev": 111, "name": "Nyíregyháza"},
        "kecskemet": {"lat": 46.8964, "lon": 19.6897, "elev": 120, "name": "Kecskemét"},
        "szekesfehervar": {"lat": 47.1860, "lon": 18.4221, "elev": 108, "name": "Székesfehérvár"},
        "szombathely": {"lat": 47.2307, "lon": 16.6218, "elev": 209, "name": "Szombathely"},
    },

    # Romania (RO)
    "RO": {
        "bucharest": {"lat": 44.4268, "lon": 26.1025, "elev": 55, "name": "București"},
        "bucuresti": {"lat": 44.4268, "lon": 26.1025, "elev": 55, "name": "București"},
        "bucurești": {"lat": 44.4268, "lon": 26.1025, "elev": 55, "name": "București"},
        "cluj-napoca": {"lat": 46.7712, "lon": 23.6236, "elev": 410, "name": "Cluj-Napoca"},
        "timisoara": {"lat": 45.7489, "lon": 21.2087, "elev": 90, "name": "Timișoara"},
        "timișoara": {"lat": 45.7489, "lon": 21.2087, "elev": 90, "name": "Timișoara"},
        "iasi": {"lat": 47.1585, "lon": 27.6014, "elev": 40, "name": "Iași"},
        "iași": {"lat": 47.1585, "lon": 27.6014, "elev": 40, "name": "Iași"},
        "constanta": {"lat": 44.1598, "lon": 28.6348, "elev": 25, "name": "Constanța"},
        "constanța": {"lat": 44.1598, "lon": 28.6348, "elev": 25, "name": "Constanța"},
        "craiova": {"lat": 44.3302, "lon": 23.7949, "elev": 110, "name": "Craiova"},
        "brasov": {"lat": 45.6427, "lon": 25.5887, "elev": 625, "name": "Brașov"},
        "brașov": {"lat": 45.6427, "lon": 25.5887, "elev": 625, "name": "Brașov"},
        "galati": {"lat": 45.4353, "lon": 28.0080, "elev": 12, "name": "Galați"},
        "ploiesti": {"lat": 44.9365, "lon": 26.0230, "elev": 166, "name": "Ploiești"},
        "oradea": {"lat": 47.0722, "lon": 21.9212, "elev": 126, "name": "Oradea"},
        "sibiu": {"lat": 45.7983, "lon": 24.1256, "elev": 415, "name": "Sibiu"},
        "arad": {"lat": 46.1866, "lon": 21.3123, "elev": 117, "name": "Arad"},
    },

    # Ukraine (UA)
    "UA": {
        "kyiv": {"lat": 50.4501, "lon": 30.5234, "elev": 179, "name": "Київ"},
        "kiev": {"lat": 50.4501, "lon": 30.5234, "elev": 179, "name": "Київ"},
        "kharkiv": {"lat": 49.9935, "lon": 36.2304, "elev": 152, "name": "Харків"},
        "odesa": {"lat": 46.4825, "lon": 30.7233, "elev": 40, "name": "Одеса"},
        "odessa": {"lat": 46.4825, "lon": 30.7233, "elev": 40, "name": "Одеса"},
        "dnipro": {"lat": 48.4647, "lon": 35.0462, "elev": 68, "name": "Дніпро"},
        "lviv": {"lat": 49.8397, "lon": 24.0297, "elev": 289, "name": "Львів"},
        "zaporizhzhia": {"lat": 47.8388, "lon": 35.1396, "elev": 60, "name": "Запоріжжя"},
        "kryvyi rih": {"lat": 47.9086, "lon": 33.3433, "elev": 85, "name": "Кривий Ріг"},
        "mykolaiv": {"lat": 46.9659, "lon": 31.9974, "elev": 7, "name": "Миколаїв"},
        "vinnytsia": {"lat": 49.2331, "lon": 28.4682, "elev": 294, "name": "Вінниця"},
        "kherson": {"lat": 46.6354, "lon": 32.6169, "elev": 20, "name": "Херсон"},
        "poltava": {"lat": 49.5883, "lon": 34.5514, "elev": 160, "name": "Полтава"},
        "chernihiv": {"lat": 51.4982, "lon": 31.2893, "elev": 117, "name": "Чернігів"},
    },

    # United Kingdom (GB)
    "GB": {
        "london": {"lat": 51.5074, "lon": -0.1278, "elev": 11, "name": "London"},
        "londyn": {"lat": 51.5074, "lon": -0.1278, "elev": 11, "name": "London"},  # Polish
        "birmingham": {"lat": 52.4862, "lon": -1.8904, "elev": 140, "name": "Birmingham"},
        "manchester": {"lat": 53.4808, "lon": -2.2426, "elev": 38, "name": "Manchester"},
        "leeds": {"lat": 53.8008, "lon": -1.5491, "elev": 63, "name": "Leeds"},
        "glasgow": {"lat": 55.8642, "lon": -4.2518, "elev": 40, "name": "Glasgow"},
        "liverpool": {"lat": 53.4084, "lon": -2.9916, "elev": 10, "name": "Liverpool"},
        "newcastle": {"lat": 54.9783, "lon": -1.6178, "elev": 42, "name": "Newcastle upon Tyne"},
        "sheffield": {"lat": 53.3811, "lon": -1.4701, "elev": 75, "name": "Sheffield"},
        "bristol": {"lat": 51.4545, "lon": -2.5879, "elev": 11, "name": "Bristol"},
        "edinburgh": {"lat": 55.9533, "lon": -3.1883, "elev": 47, "name": "Edinburgh"},
        "edynburg": {"lat": 55.9533, "lon": -3.1883, "elev": 47, "name": "Edinburgh"},  # Polish
        "cardiff": {"lat": 51.4816, "lon": -3.1791, "elev": 9, "name": "Cardiff"},
        "belfast": {"lat": 54.5973, "lon": -5.9301, "elev": 4, "name": "Belfast"},
        "nottingham": {"lat": 52.9548, "lon": -1.1581, "elev": 61, "name": "Nottingham"},
        "leicester": {"lat": 52.6369, "lon": -1.1398, "elev": 67, "name": "Leicester"},
        "coventry": {"lat": 52.4068, "lon": -1.5197, "elev": 98, "name": "Coventry"},
    },

    # Sweden (SE)
    "SE": {
        "stockholm": {"lat": 59.3293, "lon": 18.0686, "elev": 28, "name": "Stockholm"},
        "gothenburg": {"lat": 57.7089, "lon": 11.9746, "elev": 12, "name": "Göteborg"},
        "goteborg": {"lat": 57.7089, "lon": 11.9746, "elev": 12, "name": "Göteborg"},
        "göteborg": {"lat": 57.7089, "lon": 11.9746, "elev": 12, "name": "Göteborg"},
        "malmo": {"lat": 55.6050, "lon": 13.0038, "elev": 12, "name": "Malmö"},
        "malmö": {"lat": 55.6050, "lon": 13.0038, "elev": 12, "name": "Malmö"},
        "uppsala": {"lat": 59.8586, "lon": 17.6389, "elev": 14, "name": "Uppsala"},
        "vasteras": {"lat": 59.6162, "lon": 16.5528, "elev": 10, "name": "Västerås"},
        "orebro": {"lat": 59.2753, "lon": 15.2134, "elev": 27, "name": "Örebro"},
        "linkoping": {"lat": 58.4108, "lon": 15.6214, "elev": 73, "name": "Linköping"},
        "helsingborg": {"lat": 56.0465, "lon": 12.6945, "elev": 10, "name": "Helsingborg"},
        "jonkoping": {"lat": 57.7826, "lon": 14.1618, "elev": 104, "name": "Jönköping"},
        "norrkoping": {"lat": 58.5877, "lon": 16.1924, "elev": 14, "name": "Norrköping"},
        "lund": {"lat": 55.7047, "lon": 13.1910, "elev": 23, "name": "Lund"},
        "umea": {"lat": 63.8258, "lon": 20.2630, "elev": 12, "name": "Umeå"},
    },

    # Denmark (DK)
    "DK": {
        "copenhagen": {"lat": 55.6761, "lon": 12.5683, "elev": 9, "name": "København"},
        "kobenhavn": {"lat": 55.6761, "lon": 12.5683, "elev": 9, "name": "København"},
        "københavn": {"lat": 55.6761, "lon": 12.5683, "elev": 9, "name": "København"},
        "aarhus": {"lat": 56.1629, "lon": 10.2039, "elev": 0, "name": "Aarhus"},
        "odense": {"lat": 55.4038, "lon": 10.4024, "elev": 13, "name": "Odense"},
        "aalborg": {"lat": 57.0488, "lon": 9.9217, "elev": 3, "name": "Aalborg"},
        "esbjerg": {"lat": 55.4670, "lon": 8.4522, "elev": 3, "name": "Esbjerg"},
        "randers": {"lat": 56.4607, "lon": 10.0362, "elev": 8, "name": "Randers"},
        "kolding": {"lat": 55.4904, "lon": 9.4722, "elev": 19, "name": "Kolding"},
        "horsens": {"lat": 55.8607, "lon": 9.8503, "elev": 8, "name": "Horsens"},
        "vejle": {"lat": 55.7113, "lon": 9.5364, "elev": 8, "name": "Vejle"},
    },

    # Norway (NO)
    "NO": {
        "oslo": {"lat": 59.9139, "lon": 10.7522, "elev": 23, "name": "Oslo"},
        "bergen": {"lat": 60.3913, "lon": 5.3221, "elev": 12, "name": "Bergen"},
        "trondheim": {"lat": 63.4305, "lon": 10.3951, "elev": 15, "name": "Trondheim"},
        "stavanger": {"lat": 58.9700, "lon": 5.7331, "elev": 10, "name": "Stavanger"},
        "drammen": {"lat": 59.7440, "lon": 10.2045, "elev": 6, "name": "Drammen"},
        "fredrikstad": {"lat": 59.2181, "lon": 10.9298, "elev": 5, "name": "Fredrikstad"},
        "kristiansand": {"lat": 58.1599, "lon": 8.0182, "elev": 7, "name": "Kristiansand"},
        "sandnes": {"lat": 58.8521, "lon": 5.7352, "elev": 10, "name": "Sandnes"},
        "tromso": {"lat": 69.6492, "lon": 18.9553, "elev": 10, "name": "Tromsø"},
        "tromsø": {"lat": 69.6492, "lon": 18.9553, "elev": 10, "name": "Tromsø"},
    },

    # Finland (FI)
    "FI": {
        "helsinki": {"lat": 60.1699, "lon": 24.9384, "elev": 26, "name": "Helsinki"},
        "espoo": {"lat": 60.2055, "lon": 24.6559, "elev": 25, "name": "Espoo"},
        "tampere": {"lat": 61.4978, "lon": 23.7610, "elev": 114, "name": "Tampere"},
        "vantaa": {"lat": 60.2934, "lon": 25.0378, "elev": 51, "name": "Vantaa"},
        "oulu": {"lat": 65.0121, "lon": 25.4651, "elev": 15, "name": "Oulu"},
        "turku": {"lat": 60.4518, "lon": 22.2666, "elev": 3, "name": "Turku"},
        "jyvaskyla": {"lat": 62.2426, "lon": 25.7473, "elev": 86, "name": "Jyväskylä"},
        "lahti": {"lat": 60.9827, "lon": 25.6612, "elev": 81, "name": "Lahti"},
        "kuopio": {"lat": 62.8924, "lon": 27.6770, "elev": 82, "name": "Kuopio"},
        "pori": {"lat": 61.4851, "lon": 21.7974, "elev": 12, "name": "Pori"},
    },

    # Portugal (PT)
    "PT": {
        "lisbon": {"lat": 38.7223, "lon": -9.1393, "elev": 2, "name": "Lisboa"},
        "lisboa": {"lat": 38.7223, "lon": -9.1393, "elev": 2, "name": "Lisboa"},
        "porto": {"lat": 41.1579, "lon": -8.6291, "elev": 104, "name": "Porto"},
        "braga": {"lat": 41.5518, "lon": -8.4229, "elev": 190, "name": "Braga"},
        "amadora": {"lat": 38.7597, "lon": -9.2395, "elev": 125, "name": "Amadora"},
        "coimbra": {"lat": 40.2033, "lon": -8.4103, "elev": 75, "name": "Coimbra"},
        "funchal": {"lat": 32.6669, "lon": -16.9241, "elev": 25, "name": "Funchal"},
        "setubal": {"lat": 38.5244, "lon": -8.8882, "elev": 8, "name": "Setúbal"},
        "faro": {"lat": 37.0194, "lon": -7.9322, "elev": 8, "name": "Faro"},
        "aveiro": {"lat": 40.6443, "lon": -8.6455, "elev": 7, "name": "Aveiro"},
    },

    # Greece (GR)
    "GR": {
        "athens": {"lat": 37.9838, "lon": 23.7275, "elev": 70, "name": "Αθήνα"},
        "athina": {"lat": 37.9838, "lon": 23.7275, "elev": 70, "name": "Αθήνα"},
        "thessaloniki": {"lat": 40.6401, "lon": 22.9444, "elev": 5, "name": "Θεσσαλονίκη"},
        "patras": {"lat": 38.2466, "lon": 21.7346, "elev": 3, "name": "Πάτρα"},
        "heraklion": {"lat": 35.3387, "lon": 25.1442, "elev": 35, "name": "Ηράκλειο"},
        "larissa": {"lat": 39.6390, "lon": 22.4191, "elev": 73, "name": "Λάρισα"},
        "volos": {"lat": 39.3666, "lon": 22.9420, "elev": 3, "name": "Βόλος"},
        "ioannina": {"lat": 39.6650, "lon": 20.8537, "elev": 480, "name": "Ιωάννινα"},
        "kavala": {"lat": 40.9397, "lon": 24.4014, "elev": 5, "name": "Καβάλα"},
        "rhodes": {"lat": 36.4349, "lon": 28.2176, "elev": 10, "name": "Ρόδος"},
    },

    # Ireland (IE)
    "IE": {
        "dublin": {"lat": 53.3498, "lon": -6.2603, "elev": 8, "name": "Dublin"},
        "cork": {"lat": 51.8985, "lon": -8.4756, "elev": 10, "name": "Cork"},
        "limerick": {"lat": 52.6638, "lon": -8.6267, "elev": 10, "name": "Limerick"},
        "galway": {"lat": 53.2707, "lon": -9.0568, "elev": 5, "name": "Galway"},
        "waterford": {"lat": 52.2593, "lon": -7.1101, "elev": 6, "name": "Waterford"},
        "drogheda": {"lat": 53.7179, "lon": -6.3561, "elev": 15, "name": "Drogheda"},
        "kilkenny": {"lat": 52.6541, "lon": -7.2448, "elev": 60, "name": "Kilkenny"},
    },

    # Croatia (HR)
    "HR": {
        "zagreb": {"lat": 45.8150, "lon": 15.9819, "elev": 122, "name": "Zagreb"},
        "split": {"lat": 43.5081, "lon": 16.4402, "elev": 0, "name": "Split"},
        "rijeka": {"lat": 45.3271, "lon": 14.4422, "elev": 0, "name": "Rijeka"},
        "osijek": {"lat": 45.5550, "lon": 18.6955, "elev": 94, "name": "Osijek"},
        "zadar": {"lat": 44.1194, "lon": 15.2314, "elev": 5, "name": "Zadar"},
        "pula": {"lat": 44.8666, "lon": 13.8496, "elev": 30, "name": "Pula"},
        "dubrovnik": {"lat": 42.6507, "lon": 18.0944, "elev": 3, "name": "Dubrovnik"},
    },

    # Slovenia (SI)
    "SI": {
        "ljubljana": {"lat": 46.0569, "lon": 14.5058, "elev": 295, "name": "Ljubljana"},
        "maribor": {"lat": 46.5547, "lon": 15.6459, "elev": 275, "name": "Maribor"},
        "celje": {"lat": 46.2389, "lon": 15.2677, "elev": 241, "name": "Celje"},
        "kranj": {"lat": 46.2389, "lon": 14.3556, "elev": 385, "name": "Kranj"},
        "koper": {"lat": 45.5469, "lon": 13.7294, "elev": 5, "name": "Koper"},
        "novo mesto": {"lat": 45.8042, "lon": 15.1689, "elev": 202, "name": "Novo mesto"},
    },

    # Lithuania (LT)
    "LT": {
        "vilnius": {"lat": 54.6872, "lon": 25.2797, "elev": 112, "name": "Vilnius"},
        "kaunas": {"lat": 54.8985, "lon": 23.9036, "elev": 73, "name": "Kaunas"},
        "klaipeda": {"lat": 55.7033, "lon": 21.1443, "elev": 21, "name": "Klaipėda"},
        "siauliai": {"lat": 55.9349, "lon": 23.3137, "elev": 130, "name": "Šiauliai"},
        "panevezys": {"lat": 55.7348, "lon": 24.3575, "elev": 60, "name": "Panevėžys"},
    },

    # Latvia (LV)
    "LV": {
        "riga": {"lat": 56.9496, "lon": 24.1052, "elev": 6, "name": "Rīga"},
        "daugavpils": {"lat": 55.8714, "lon": 26.5161, "elev": 111, "name": "Daugavpils"},
        "liepaja": {"lat": 56.5047, "lon": 21.0108, "elev": 8, "name": "Liepāja"},
        "jelgava": {"lat": 56.6511, "lon": 23.7211, "elev": 3, "name": "Jelgava"},
        "jurmala": {"lat": 56.9680, "lon": 23.7703, "elev": 5, "name": "Jūrmala"},
    },

    # Estonia (EE)
    "EE": {
        "tallinn": {"lat": 59.4370, "lon": 24.7536, "elev": 9, "name": "Tallinn"},
        "tartu": {"lat": 58.3780, "lon": 26.7290, "elev": 67, "name": "Tartu"},
        "narva": {"lat": 59.3797, "lon": 28.1791, "elev": 27, "name": "Narva"},
        "parnu": {"lat": 58.3859, "lon": 24.4971, "elev": 5, "name": "Pärnu"},
        "kohtla-jarve": {"lat": 59.3983, "lon": 27.2731, "elev": 50, "name": "Kohtla-Järve"},
    },

    # Bulgaria (BG)
    "BG": {
        "sofia": {"lat": 42.6977, "lon": 23.3219, "elev": 550, "name": "София"},
        "plovdiv": {"lat": 42.1354, "lon": 24.7453, "elev": 164, "name": "Пловдив"},
        "varna": {"lat": 43.2141, "lon": 27.9147, "elev": 80, "name": "Варна"},
        "burgas": {"lat": 42.5048, "lon": 27.4626, "elev": 16, "name": "Бургас"},
        "ruse": {"lat": 43.8356, "lon": 25.9657, "elev": 45, "name": "Русе"},
        "stara zagora": {"lat": 42.4258, "lon": 25.6345, "elev": 196, "name": "Стара Загора"},
    },

    # Serbia (RS)
    "RS": {
        "belgrade": {"lat": 44.7866, "lon": 20.4489, "elev": 116, "name": "Beograd"},
        "beograd": {"lat": 44.7866, "lon": 20.4489, "elev": 116, "name": "Beograd"},
        "novi sad": {"lat": 45.2671, "lon": 19.8335, "elev": 80, "name": "Novi Sad"},
        "nis": {"lat": 43.3209, "lon": 21.8958, "elev": 194, "name": "Niš"},
        "niš": {"lat": 43.3209, "lon": 21.8958, "elev": 194, "name": "Niš"},
        "kragujevac": {"lat": 44.0128, "lon": 20.9114, "elev": 185, "name": "Kragujevac"},
        "subotica": {"lat": 46.1000, "lon": 19.6658, "elev": 114, "name": "Subotica"},
    },
}

# Country name to ISO code mapping
COUNTRY_NAME_TO_CODE = {
    "germany": "DE",
    "deutschland": "DE",
    "niemcy": "DE",
    "czech republic": "CZ",
    "czechia": "CZ",
    "česká republika": "CZ",
    "ceska republika": "CZ",
    "czechy": "CZ",
    "slovakia": "SK",
    "slovensko": "SK",
    "słowacja": "SK",
    "austria": "AT",
    "österreich": "AT",
    "osterreich": "AT",
    "france": "FR",
    "francja": "FR",
    "italy": "IT",
    "italia": "IT",
    "włochy": "IT",
    "spain": "ES",
    "españa": "ES",
    "espana": "ES",
    "hiszpania": "ES",
    "netherlands": "NL",
    "holland": "NL",
    "holandia": "NL",
    "belgium": "BE",
    "belgique": "BE",
    "belgia": "BE",
    "switzerland": "CH",
    "schweiz": "CH",
    "suisse": "CH",
    "szwajcaria": "CH",
    "hungary": "HU",
    "magyarország": "HU",
    "węgry": "HU",
    "romania": "RO",
    "românia": "RO",
    "rumunia": "RO",
    "ukraine": "UA",
    "україна": "UA",
    "ukraina": "UA",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "wielka brytania": "GB",
    "anglia": "GB",
    "sweden": "SE",
    "sverige": "SE",
    "szwecja": "SE",
    "denmark": "DK",
    "danmark": "DK",
    "dania": "DK",
    "norway": "NO",
    "norge": "NO",
    "norwegia": "NO",
    "finland": "FI",
    "suomi": "FI",
    "finlandia": "FI",
    "portugal": "PT",
    "portugalia": "PT",
    "greece": "GR",
    "ελλάδα": "GR",
    "grecja": "GR",
    "ireland": "IE",
    "éire": "IE",
    "irlandia": "IE",
    "croatia": "HR",
    "hrvatska": "HR",
    "chorwacja": "HR",
    "slovenia": "SI",
    "slovenija": "SI",
    "słowenia": "SI",
    "lithuania": "LT",
    "lietuva": "LT",
    "litwa": "LT",
    "latvia": "LV",
    "latvija": "LV",
    "łotwa": "LV",
    "estonia": "EE",
    "eesti": "EE",
    "bulgaria": "BG",
    "българия": "BG",
    "bułgaria": "BG",
    "serbia": "RS",
    "србија": "RS",
}


def lookup_european_city(country_code: str, city_name: str) -> dict | None:
    """
    Look up a European city by country code and city name.
    Returns dict with lat, lon, elev, name or None if not found.
    """
    country_code = country_code.upper()

    # Normalize country code if full name given
    if country_code.lower() in COUNTRY_NAME_TO_CODE:
        country_code = COUNTRY_NAME_TO_CODE[country_code.lower()]

    if country_code not in EUROPEAN_CITIES:
        return None

    city_lower = city_name.lower().strip()
    country_cities = EUROPEAN_CITIES[country_code]

    if city_lower in country_cities:
        data = country_cities[city_lower]
        return {
            "lat": data["lat"],
            "lon": data["lon"],
            "elev": data["elev"],
            "city": data["name"],
            "country": country_code
        }

    return None


def get_supported_countries() -> list[str]:
    """Return list of supported country codes."""
    return list(EUROPEAN_CITIES.keys())


def get_cities_for_country(country_code: str) -> list[str]:
    """Return list of city names for a country."""
    country_code = country_code.upper()
    if country_code in EUROPEAN_CITIES:
        return sorted(set(d["name"] for d in EUROPEAN_CITIES[country_code].values()))
    return []


# Statistics
STATS = {
    "countries": len(EUROPEAN_CITIES),
    "total_cities": sum(len(set(d["name"] for d in cities.values())) for cities in EUROPEAN_CITIES.values()),
}
