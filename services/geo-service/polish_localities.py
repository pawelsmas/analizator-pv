"""
Comprehensive Polish Localities Database
Contains ~2500 localities with postal codes and coordinates for PV Optimizer.

Structure:
- POLISH_LOCALITIES: Dict mapping city name (lowercase) to {lat, lon, elev, postal_code}
- POSTAL_CODE_TO_CITY: Dict mapping postal code to primary city name and coordinates

Data source: OpenStreetMap, GUS (Główny Urząd Statystyczny)
"""

# ============================================
# WOJEWÓDZKIE - Capitals of voivodeships (16)
# ============================================
VOIVODESHIP_CAPITALS = {
    "warszawa": {"lat": 52.2297, "lon": 21.0122, "elev": 100, "postal": "00-001", "woj": "mazowieckie"},
    "kraków": {"lat": 50.0647, "lon": 19.9450, "elev": 219, "postal": "30-001", "woj": "małopolskie"},
    "łódź": {"lat": 51.7592, "lon": 19.4560, "elev": 200, "postal": "90-001", "woj": "łódzkie"},
    "wrocław": {"lat": 51.1079, "lon": 17.0385, "elev": 120, "postal": "50-001", "woj": "dolnośląskie"},
    "poznań": {"lat": 52.4064, "lon": 16.9252, "elev": 60, "postal": "60-001", "woj": "wielkopolskie"},
    "gdańsk": {"lat": 54.3520, "lon": 18.6466, "elev": 10, "postal": "80-001", "woj": "pomorskie"},
    "szczecin": {"lat": 53.4285, "lon": 14.5528, "elev": 25, "postal": "70-001", "woj": "zachodniopomorskie"},
    "bydgoszcz": {"lat": 53.1235, "lon": 18.0084, "elev": 60, "postal": "85-001", "woj": "kujawsko-pomorskie"},
    "lublin": {"lat": 51.2465, "lon": 22.5684, "elev": 200, "postal": "20-001", "woj": "lubelskie"},
    "białystok": {"lat": 53.1325, "lon": 23.1688, "elev": 150, "postal": "15-001", "woj": "podlaskie"},
    "katowice": {"lat": 50.2649, "lon": 19.0238, "elev": 280, "postal": "40-001", "woj": "śląskie"},
    "kielce": {"lat": 50.8661, "lon": 20.6286, "elev": 260, "postal": "25-001", "woj": "świętokrzyskie"},
    "rzeszów": {"lat": 50.0412, "lon": 21.9991, "elev": 220, "postal": "35-001", "woj": "podkarpackie"},
    "olsztyn": {"lat": 53.7784, "lon": 20.4801, "elev": 130, "postal": "10-001", "woj": "warmińsko-mazurskie"},
    "opole": {"lat": 50.6751, "lon": 17.9213, "elev": 155, "postal": "45-001", "woj": "opolskie"},
    "gorzów wielkopolski": {"lat": 52.7368, "lon": 15.2288, "elev": 40, "postal": "66-400", "woj": "lubuskie"},
    "zielona góra": {"lat": 51.9356, "lon": 15.5062, "elev": 80, "postal": "65-001", "woj": "lubuskie"},
    "toruń": {"lat": 53.0138, "lon": 18.5984, "elev": 65, "postal": "87-100", "woj": "kujawsko-pomorskie"},
}

# ============================================
# MIASTA POWIATOWE I WIĘKSZE MIEJSCOWOŚCI
# Sorted alphabetically for easy lookup
# ============================================
POLISH_LOCALITIES = {
    # A
    "aleksandrów kujawski": {"lat": 52.8750, "lon": 18.6944, "elev": 50, "postal": "87-700"},
    "aleksandrów łódzki": {"lat": 51.8194, "lon": 19.3031, "elev": 180, "postal": "95-070"},
    "andrychów": {"lat": 49.8544, "lon": 19.3364, "elev": 340, "postal": "34-120"},
    "augustów": {"lat": 53.8433, "lon": 22.9797, "elev": 125, "postal": "16-300"},

    # B
    "bartoszyce": {"lat": 54.2528, "lon": 20.8094, "elev": 50, "postal": "11-200"},
    "bełchatów": {"lat": 51.3675, "lon": 19.3558, "elev": 180, "postal": "97-400"},
    "będzin": {"lat": 50.3125, "lon": 19.1297, "elev": 280, "postal": "42-500"},
    "biała podlaska": {"lat": 52.0325, "lon": 23.1164, "elev": 140, "postal": "21-500"},
    "białogard": {"lat": 54.0042, "lon": 15.9872, "elev": 25, "postal": "78-200"},
    "bielsk podlaski": {"lat": 52.7650, "lon": 23.1919, "elev": 155, "postal": "17-100"},
    "bielsko-biała": {"lat": 49.8224, "lon": 19.0444, "elev": 340, "postal": "43-300"},
    "biłgoraj": {"lat": 50.5417, "lon": 22.7228, "elev": 210, "postal": "23-400"},
    "bochnia": {"lat": 49.9692, "lon": 20.4317, "elev": 210, "postal": "32-700"},
    "bolesławiec": {"lat": 51.2650, "lon": 15.5692, "elev": 210, "postal": "59-700"},
    "braniewo": {"lat": 54.3806, "lon": 19.8239, "elev": 15, "postal": "14-500"},
    "brodnica": {"lat": 53.2578, "lon": 19.3994, "elev": 85, "postal": "87-300"},
    "brzeg": {"lat": 50.8608, "lon": 17.4667, "elev": 145, "postal": "49-300"},
    "brzesko": {"lat": 49.9683, "lon": 20.6092, "elev": 210, "postal": "32-800"},
    "brzeziny": {"lat": 51.8022, "lon": 19.7531, "elev": 185, "postal": "95-060"},
    "busko-zdrój": {"lat": 50.4703, "lon": 20.7194, "elev": 240, "postal": "28-100"},
    "bytom": {"lat": 50.3483, "lon": 18.9156, "elev": 300, "postal": "41-900"},
    "bytów": {"lat": 54.1689, "lon": 17.4939, "elev": 160, "postal": "77-100"},

    # C
    "chełm": {"lat": 51.1322, "lon": 23.4717, "elev": 190, "postal": "22-100"},
    "chełmno": {"lat": 53.3492, "lon": 18.4258, "elev": 30, "postal": "86-200"},
    "chodzież": {"lat": 52.9925, "lon": 16.9197, "elev": 80, "postal": "64-800"},
    "chojnice": {"lat": 53.6972, "lon": 17.5594, "elev": 160, "postal": "89-600"},
    "chorzów": {"lat": 50.2975, "lon": 18.9542, "elev": 285, "postal": "41-500"},
    "choszczno": {"lat": 53.1658, "lon": 15.4144, "elev": 65, "postal": "73-200"},
    "ciechanów": {"lat": 52.8808, "lon": 20.6200, "elev": 130, "postal": "06-400"},
    "cieszyn": {"lat": 49.7500, "lon": 18.6328, "elev": 300, "postal": "43-400"},
    "czarnków": {"lat": 52.9017, "lon": 16.5622, "elev": 50, "postal": "64-700"},
    "częstochowa": {"lat": 50.8118, "lon": 19.1203, "elev": 260, "postal": "42-200"},
    "człuchów": {"lat": 53.6600, "lon": 17.3617, "elev": 140, "postal": "77-300"},

    # D
    "dąbrowa górnicza": {"lat": 50.3217, "lon": 19.1947, "elev": 300, "postal": "41-300"},
    "dębica": {"lat": 50.0536, "lon": 21.4108, "elev": 230, "postal": "39-200"},
    "dęblin": {"lat": 51.5575, "lon": 21.8525, "elev": 130, "postal": "08-530"},
    "drawsko pomorskie": {"lat": 53.5322, "lon": 15.8053, "elev": 90, "postal": "78-500"},
    "działdowo": {"lat": 53.2369, "lon": 20.1756, "elev": 150, "postal": "13-200"},
    "dzierżoniów": {"lat": 50.7278, "lon": 16.6511, "elev": 280, "postal": "58-200"},

    # E
    "elbląg": {"lat": 54.1561, "lon": 19.4044, "elev": 10, "postal": "82-300"},
    "ełk": {"lat": 53.8283, "lon": 22.3647, "elev": 150, "postal": "19-300"},

    # G
    "garwolin": {"lat": 51.8964, "lon": 21.6119, "elev": 140, "postal": "08-400"},
    "gdynia": {"lat": 54.5189, "lon": 18.5319, "elev": 15, "postal": "81-300"},
    "giżycko": {"lat": 54.0383, "lon": 21.7647, "elev": 120, "postal": "11-500"},
    "gliwice": {"lat": 50.2945, "lon": 18.6714, "elev": 230, "postal": "44-100"},
    "głogów": {"lat": 51.6631, "lon": 16.0847, "elev": 80, "postal": "67-200"},
    "głubczyce": {"lat": 50.2008, "lon": 17.8297, "elev": 270, "postal": "48-100"},
    "gniezno": {"lat": 52.5347, "lon": 17.5828, "elev": 115, "postal": "62-200"},
    "goleniów": {"lat": 53.5622, "lon": 14.8278, "elev": 15, "postal": "72-100"},
    "golub-dobrzyń": {"lat": 53.1094, "lon": 19.0536, "elev": 80, "postal": "87-400"},
    "gorzów wielkopolski": {"lat": 52.7368, "lon": 15.2288, "elev": 40, "postal": "66-400"},
    "gostyń": {"lat": 51.8797, "lon": 17.0147, "elev": 90, "postal": "63-800"},
    "góra": {"lat": 51.6681, "lon": 16.5433, "elev": 100, "postal": "56-200"},
    "grajewo": {"lat": 53.6472, "lon": 22.4606, "elev": 125, "postal": "19-200"},
    "grodzisk mazowiecki": {"lat": 52.1106, "lon": 20.6303, "elev": 100, "postal": "05-825"},
    "grodzisk wielkopolski": {"lat": 52.2269, "lon": 16.3650, "elev": 85, "postal": "62-065"},
    "grójec": {"lat": 51.8653, "lon": 20.8678, "elev": 150, "postal": "05-600"},
    "grudziądz": {"lat": 53.4839, "lon": 18.7536, "elev": 35, "postal": "86-300"},
    "gryfice": {"lat": 53.9169, "lon": 15.1983, "elev": 15, "postal": "72-300"},
    "gryfino": {"lat": 53.2522, "lon": 14.4886, "elev": 10, "postal": "74-100"},

    # H
    "hajnówka": {"lat": 52.7433, "lon": 23.5858, "elev": 170, "postal": "17-200"},
    "hrubieszów": {"lat": 50.8050, "lon": 23.8914, "elev": 195, "postal": "22-500"},

    # I
    "iława": {"lat": 53.5986, "lon": 19.5672, "elev": 115, "postal": "14-200"},
    "inowrocław": {"lat": 52.7939, "lon": 18.2606, "elev": 90, "postal": "88-100"},

    # J
    "janów lubelski": {"lat": 50.7083, "lon": 22.4167, "elev": 220, "postal": "23-300"},
    "jarocin": {"lat": 51.9711, "lon": 17.5031, "elev": 100, "postal": "63-200"},
    "jarosław": {"lat": 50.0169, "lon": 22.6778, "elev": 210, "postal": "37-500"},
    "jasło": {"lat": 49.7447, "lon": 21.4711, "elev": 240, "postal": "38-200"},
    "jastrzębie-zdrój": {"lat": 49.9506, "lon": 18.6100, "elev": 290, "postal": "44-330"},
    "jawor": {"lat": 51.0536, "lon": 16.1939, "elev": 190, "postal": "59-400"},
    "jaworzno": {"lat": 50.2053, "lon": 19.2747, "elev": 280, "postal": "43-600"},
    "jelenia góra": {"lat": 50.9044, "lon": 15.7281, "elev": 350, "postal": "58-500"},
    "jędrzejów": {"lat": 50.6450, "lon": 20.3028, "elev": 275, "postal": "28-300"},

    # K
    "kalisz": {"lat": 51.7611, "lon": 18.0853, "elev": 105, "postal": "62-800"},
    "kamienna góra": {"lat": 50.7839, "lon": 16.0289, "elev": 470, "postal": "58-400"},
    "kamień pomorski": {"lat": 53.9689, "lon": 14.7736, "elev": 5, "postal": "72-400"},
    "kartuzy": {"lat": 54.3347, "lon": 18.1978, "elev": 190, "postal": "83-300"},
    "kędzierzyn-koźle": {"lat": 50.3494, "lon": 18.2064, "elev": 185, "postal": "47-200"},
    "kępno": {"lat": 51.2786, "lon": 17.9861, "elev": 175, "postal": "63-600"},
    "kętrzyn": {"lat": 54.0764, "lon": 21.3744, "elev": 110, "postal": "11-400"},
    "kluczbork": {"lat": 50.9736, "lon": 18.2167, "elev": 185, "postal": "46-200"},
    "koło": {"lat": 52.2008, "lon": 18.6378, "elev": 100, "postal": "62-600"},
    "kołobrzeg": {"lat": 54.1756, "lon": 15.5831, "elev": 5, "postal": "78-100"},
    "konin": {"lat": 52.2231, "lon": 18.2511, "elev": 90, "postal": "62-500"},
    "końskie": {"lat": 51.1903, "lon": 20.4139, "elev": 240, "postal": "26-200"},
    "koszalin": {"lat": 54.1944, "lon": 16.1722, "elev": 30, "postal": "75-001"},
    "kościan": {"lat": 52.0867, "lon": 16.6478, "elev": 80, "postal": "64-000"},
    "kościerzyna": {"lat": 54.1217, "lon": 17.9778, "elev": 180, "postal": "83-400"},
    "kozienice": {"lat": 51.5844, "lon": 21.5539, "elev": 120, "postal": "26-900"},
    "krasnystaw": {"lat": 50.9844, "lon": 23.1731, "elev": 200, "postal": "22-300"},
    "kraśnik": {"lat": 50.9236, "lon": 22.2256, "elev": 210, "postal": "23-200"},
    "krosno": {"lat": 49.6886, "lon": 21.7706, "elev": 280, "postal": "38-400"},
    "krotoszyn": {"lat": 51.6972, "lon": 17.4375, "elev": 130, "postal": "63-700"},
    "kutno": {"lat": 52.2311, "lon": 19.3572, "elev": 105, "postal": "99-300"},
    "kwidzyn": {"lat": 53.7331, "lon": 18.9311, "elev": 20, "postal": "82-500"},

    # L
    "legionowo": {"lat": 52.4011, "lon": 20.9261, "elev": 80, "postal": "05-120"},
    "legnica": {"lat": 51.2100, "lon": 16.1619, "elev": 115, "postal": "59-220"},
    "leszno": {"lat": 51.8419, "lon": 16.5747, "elev": 90, "postal": "64-100"},
    "lębork": {"lat": 54.5389, "lon": 17.7486, "elev": 30, "postal": "84-300"},
    "lidzbark warmiński": {"lat": 54.1267, "lon": 20.5789, "elev": 65, "postal": "11-100"},
    "limanowa": {"lat": 49.7022, "lon": 20.4256, "elev": 410, "postal": "34-600"},
    "lipno": {"lat": 52.8481, "lon": 19.1739, "elev": 75, "postal": "87-600"},
    "lipsko": {"lat": 51.1617, "lon": 21.6561, "elev": 150, "postal": "27-300"},
    "lubaczów": {"lat": 50.1553, "lon": 23.1219, "elev": 240, "postal": "37-600"},
    "lubań": {"lat": 51.1175, "lon": 15.2911, "elev": 270, "postal": "59-800"},
    "lubartów": {"lat": 51.4619, "lon": 22.6044, "elev": 170, "postal": "21-100"},
    "lubawka": {"lat": 50.7044, "lon": 16.0003, "elev": 420, "postal": "58-420"},
    "lubliniec": {"lat": 50.6708, "lon": 18.6833, "elev": 260, "postal": "42-700"},
    "luboń": {"lat": 52.3475, "lon": 16.8750, "elev": 65, "postal": "62-030"},
    "lwówek śląski": {"lat": 51.1136, "lon": 15.5858, "elev": 260, "postal": "59-600"},

    # Ł
    "łańcut": {"lat": 50.0683, "lon": 22.2314, "elev": 210, "postal": "37-100"},
    "łask": {"lat": 51.5911, "lon": 19.1361, "elev": 170, "postal": "98-100"},
    "łęczna": {"lat": 51.2986, "lon": 22.8847, "elev": 170, "postal": "21-010"},
    "łęczyca": {"lat": 52.0583, "lon": 19.2036, "elev": 115, "postal": "99-100"},
    "łobez": {"lat": 53.6361, "lon": 15.6236, "elev": 35, "postal": "73-150"},
    "łomża": {"lat": 53.1781, "lon": 22.0589, "elev": 130, "postal": "18-400"},
    "łowicz": {"lat": 52.1064, "lon": 19.9436, "elev": 90, "postal": "99-400"},
    "łuków": {"lat": 51.9289, "lon": 22.3831, "elev": 160, "postal": "21-400"},

    # M
    "maków mazowiecki": {"lat": 52.8647, "lon": 21.0944, "elev": 105, "postal": "06-200"},
    "malbork": {"lat": 54.0353, "lon": 19.0281, "elev": 10, "postal": "82-200"},
    "mielec": {"lat": 50.2872, "lon": 21.4261, "elev": 180, "postal": "39-300"},
    "międzychód": {"lat": 52.5936, "lon": 15.8961, "elev": 50, "postal": "64-400"},
    "międzyrzec podlaski": {"lat": 51.9864, "lon": 22.7825, "elev": 155, "postal": "21-560"},
    "międzyrzecz": {"lat": 52.4453, "lon": 15.5778, "elev": 55, "postal": "66-300"},
    "mikołów": {"lat": 50.1742, "lon": 18.9056, "elev": 290, "postal": "43-190"},
    "mińsk mazowiecki": {"lat": 52.1797, "lon": 21.5608, "elev": 170, "postal": "05-300"},
    "mława": {"lat": 53.1122, "lon": 20.3831, "elev": 140, "postal": "06-500"},
    "mogielnica": {"lat": 51.7083, "lon": 20.7269, "elev": 160, "postal": "05-640"},
    "mogilno": {"lat": 52.6614, "lon": 17.9536, "elev": 95, "postal": "88-300"},
    "mońki": {"lat": 53.4036, "lon": 22.8022, "elev": 140, "postal": "19-100"},
    "mrągowo": {"lat": 53.8669, "lon": 21.3050, "elev": 135, "postal": "11-700"},
    "mszana dolna": {"lat": 49.6694, "lon": 20.0789, "elev": 390, "postal": "34-730"},
    "myślenice": {"lat": 49.8336, "lon": 19.9392, "elev": 310, "postal": "32-400"},
    "mysłowice": {"lat": 50.2083, "lon": 19.1661, "elev": 280, "postal": "41-400"},
    "myślibórz": {"lat": 52.9239, "lon": 14.8608, "elev": 45, "postal": "74-300"},

    # N
    "nakło nad notecią": {"lat": 53.1422, "lon": 17.5981, "elev": 55, "postal": "89-100"},
    "namysłów": {"lat": 51.0756, "lon": 17.7233, "elev": 170, "postal": "46-100"},
    "nidzica": {"lat": 53.3603, "lon": 20.4292, "elev": 140, "postal": "13-100"},
    "nisko": {"lat": 50.5217, "lon": 22.1383, "elev": 145, "postal": "37-400"},
    "nowa ruda": {"lat": 50.5831, "lon": 16.4992, "elev": 430, "postal": "57-400"},
    "nowa sól": {"lat": 51.8028, "lon": 15.7158, "elev": 60, "postal": "67-100"},
    "nowe miasto lubawskie": {"lat": 53.4208, "lon": 19.5883, "elev": 110, "postal": "13-300"},
    "nowy dwór gdański": {"lat": 54.2200, "lon": 19.1200, "elev": 5, "postal": "82-100"},
    "nowy dwór mazowiecki": {"lat": 52.4272, "lon": 20.7158, "elev": 85, "postal": "05-100"},
    "nowy sącz": {"lat": 49.6247, "lon": 20.6875, "elev": 290, "postal": "33-300"},
    "nowy targ": {"lat": 49.4769, "lon": 20.0328, "elev": 590, "postal": "34-400"},
    "nowy tomyśl": {"lat": 52.3175, "lon": 16.1281, "elev": 75, "postal": "64-300"},
    "nysa": {"lat": 50.4747, "lon": 17.3344, "elev": 195, "postal": "48-300"},

    # O
    "oborniki": {"lat": 52.6475, "lon": 16.8144, "elev": 60, "postal": "64-600"},
    "ogrodzieniec": {"lat": 50.4500, "lon": 19.5167, "elev": 380, "postal": "42-440"},
    "oława": {"lat": 50.9453, "lon": 17.2931, "elev": 130, "postal": "55-200"},
    "oleśnica": {"lat": 51.2094, "lon": 17.3833, "elev": 150, "postal": "56-400"},
    "olkusz": {"lat": 50.2811, "lon": 19.5672, "elev": 370, "postal": "32-300"},
    "opatów": {"lat": 50.7750, "lon": 21.4253, "elev": 240, "postal": "27-500"},
    "opoczno": {"lat": 51.3786, "lon": 20.2778, "elev": 225, "postal": "26-300"},
    "ostrołęka": {"lat": 53.0842, "lon": 21.5742, "elev": 105, "postal": "07-400"},
    "ostrowiec świętokrzyski": {"lat": 50.9294, "lon": 21.3856, "elev": 230, "postal": "27-400"},
    "ostrów mazowiecka": {"lat": 52.8025, "lon": 21.8942, "elev": 110, "postal": "07-300"},
    "ostrów wielkopolski": {"lat": 51.6497, "lon": 17.8064, "elev": 130, "postal": "63-400"},
    "ostrzeszów": {"lat": 51.4272, "lon": 17.9350, "elev": 185, "postal": "63-500"},
    "oświęcim": {"lat": 50.0344, "lon": 19.2108, "elev": 235, "postal": "32-600"},
    "otwock": {"lat": 52.1050, "lon": 21.2611, "elev": 100, "postal": "05-400"},

    # P
    "pabianice": {"lat": 51.6647, "lon": 19.3528, "elev": 195, "postal": "95-200"},
    "pajęczno": {"lat": 51.1456, "lon": 18.9992, "elev": 205, "postal": "98-330"},
    "parczew": {"lat": 51.6383, "lon": 22.9056, "elev": 165, "postal": "21-200"},
    "piaseczno": {"lat": 52.0800, "lon": 21.0247, "elev": 100, "postal": "05-500"},
    "piekary śląskie": {"lat": 50.3833, "lon": 18.9444, "elev": 290, "postal": "41-940"},
    "piła": {"lat": 53.1519, "lon": 16.7386, "elev": 70, "postal": "64-920"},
    "piotrków trybunalski": {"lat": 51.4053, "lon": 19.7033, "elev": 195, "postal": "97-300"},
    "pisz": {"lat": 53.6264, "lon": 21.8133, "elev": 120, "postal": "12-200"},
    "pleszew": {"lat": 51.8931, "lon": 17.7858, "elev": 115, "postal": "63-300"},
    "płock": {"lat": 52.5464, "lon": 19.7064, "elev": 60, "postal": "09-400"},
    "płońsk": {"lat": 52.6233, "lon": 20.3756, "elev": 100, "postal": "09-100"},
    "poddębice": {"lat": 51.8903, "lon": 18.9553, "elev": 120, "postal": "99-200"},
    "polkowice": {"lat": 51.5036, "lon": 16.0700, "elev": 120, "postal": "59-100"},
    "połaniec": {"lat": 50.4317, "lon": 21.2811, "elev": 170, "postal": "28-230"},
    "proszowice": {"lat": 50.1917, "lon": 20.2886, "elev": 210, "postal": "32-100"},
    "prudnik": {"lat": 50.3219, "lon": 17.5753, "elev": 260, "postal": "48-200"},
    "pruszcz gdański": {"lat": 54.2628, "lon": 18.6344, "elev": 5, "postal": "83-000"},
    "pruszków": {"lat": 52.1708, "lon": 20.8119, "elev": 95, "postal": "05-800"},
    "przasnysz": {"lat": 53.0183, "lon": 20.8794, "elev": 135, "postal": "06-300"},
    "przemyśl": {"lat": 49.7839, "lon": 22.7678, "elev": 250, "postal": "37-700"},
    "przeworsk": {"lat": 50.0586, "lon": 22.4950, "elev": 210, "postal": "37-200"},
    "pszczyna": {"lat": 49.9789, "lon": 18.9539, "elev": 250, "postal": "43-200"},
    "puck": {"lat": 54.7181, "lon": 18.4086, "elev": 5, "postal": "84-100"},
    "puławy": {"lat": 51.4169, "lon": 21.9692, "elev": 120, "postal": "24-100"},
    "pułtusk": {"lat": 52.7033, "lon": 21.0833, "elev": 85, "postal": "06-100"},
    "pyrzyce": {"lat": 53.1450, "lon": 14.8942, "elev": 25, "postal": "74-200"},

    # R
    "racibórz": {"lat": 50.0919, "lon": 18.2194, "elev": 200, "postal": "47-400"},
    "radlin": {"lat": 50.0494, "lon": 18.4656, "elev": 265, "postal": "44-310"},
    "radom": {"lat": 51.4027, "lon": 21.1471, "elev": 180, "postal": "26-600"},
    "radomsko": {"lat": 51.0672, "lon": 19.4461, "elev": 230, "postal": "97-500"},
    "radziejów": {"lat": 52.6219, "lon": 18.5286, "elev": 80, "postal": "88-200"},
    "radzyń podlaski": {"lat": 51.7833, "lon": 22.6167, "elev": 160, "postal": "21-300"},
    "rawa mazowiecka": {"lat": 51.7647, "lon": 20.2511, "elev": 155, "postal": "96-200"},
    "rawicz": {"lat": 51.6094, "lon": 16.8586, "elev": 100, "postal": "63-900"},
    "reda": {"lat": 54.6075, "lon": 18.3494, "elev": 30, "postal": "84-240"},
    "ropczyce": {"lat": 50.0522, "lon": 21.6083, "elev": 225, "postal": "39-100"},
    "ruda śląska": {"lat": 50.2561, "lon": 18.8556, "elev": 280, "postal": "41-700"},
    "rumia": {"lat": 54.5703, "lon": 18.3900, "elev": 25, "postal": "84-230"},
    "rybnik": {"lat": 50.0972, "lon": 18.5417, "elev": 250, "postal": "44-200"},
    "rypin": {"lat": 53.0628, "lon": 19.4211, "elev": 95, "postal": "87-500"},
    "rzeszów": {"lat": 50.0412, "lon": 21.9991, "elev": 220, "postal": "35-001"},

    # S
    "sanok": {"lat": 49.5533, "lon": 22.2044, "elev": 310, "postal": "38-500"},
    "sejny": {"lat": 54.1117, "lon": 23.3553, "elev": 150, "postal": "16-500"},
    "sędziszów małopolski": {"lat": 50.0681, "lon": 21.7053, "elev": 230, "postal": "39-120"},
    "siedlce": {"lat": 52.1669, "lon": 22.2908, "elev": 150, "postal": "08-110"},
    "siemianowice śląskie": {"lat": 50.3267, "lon": 19.0294, "elev": 280, "postal": "41-100"},
    "sieradz": {"lat": 51.5956, "lon": 18.7306, "elev": 150, "postal": "98-200"},
    "sierpc": {"lat": 52.8564, "lon": 19.6694, "elev": 80, "postal": "09-200"},
    "skarżysko-kamienna": {"lat": 51.1136, "lon": 20.8606, "elev": 250, "postal": "26-110"},
    "skierniewice": {"lat": 51.9547, "lon": 20.1517, "elev": 125, "postal": "96-100"},
    "słubice": {"lat": 52.3525, "lon": 14.5606, "elev": 20, "postal": "69-100"},
    "słupca": {"lat": 52.2853, "lon": 17.8622, "elev": 90, "postal": "62-400"},
    "słupsk": {"lat": 54.4642, "lon": 17.0286, "elev": 25, "postal": "76-200"},
    "sochaczew": {"lat": 52.2247, "lon": 20.2400, "elev": 70, "postal": "96-500"},
    "sokołów podlaski": {"lat": 52.4094, "lon": 22.2550, "elev": 145, "postal": "08-300"},
    "sokółka": {"lat": 53.4078, "lon": 23.4972, "elev": 180, "postal": "16-100"},
    "sopot": {"lat": 54.4419, "lon": 18.5603, "elev": 15, "postal": "81-700"},
    "sosnowiec": {"lat": 50.2861, "lon": 19.1042, "elev": 260, "postal": "41-200"},
    "stalowa wola": {"lat": 50.5828, "lon": 22.0544, "elev": 165, "postal": "37-450"},
    "starachowice": {"lat": 51.0394, "lon": 21.0694, "elev": 240, "postal": "27-200"},
    "stargard": {"lat": 53.3361, "lon": 15.0500, "elev": 30, "postal": "73-110"},
    "starogard gdański": {"lat": 53.9636, "lon": 18.5294, "elev": 40, "postal": "83-200"},
    "staszów": {"lat": 50.5628, "lon": 21.1661, "elev": 200, "postal": "28-200"},
    "strzelce krajeńskie": {"lat": 52.8764, "lon": 15.5306, "elev": 50, "postal": "66-500"},
    "strzelce opolskie": {"lat": 50.5122, "lon": 18.2992, "elev": 200, "postal": "47-100"},
    "strzelin": {"lat": 50.7817, "lon": 17.0636, "elev": 175, "postal": "57-100"},
    "strzyżów": {"lat": 49.8681, "lon": 21.7936, "elev": 260, "postal": "38-100"},
    "suchowola": {"lat": 53.5722, "lon": 23.1039, "elev": 145, "postal": "16-150"},
    "sulechów": {"lat": 52.0831, "lon": 15.6286, "elev": 55, "postal": "66-100"},
    "sulęcin": {"lat": 52.4486, "lon": 15.1156, "elev": 65, "postal": "69-200"},
    "suwałki": {"lat": 54.1117, "lon": 22.9308, "elev": 185, "postal": "16-400"},
    "swarzędz": {"lat": 52.4111, "lon": 17.0778, "elev": 75, "postal": "62-020"},
    "świebodzice": {"lat": 50.8642, "lon": 16.3256, "elev": 330, "postal": "58-160"},
    "świebodzin": {"lat": 52.2447, "lon": 15.5333, "elev": 55, "postal": "66-200"},
    "świecie": {"lat": 53.4100, "lon": 18.4317, "elev": 25, "postal": "86-100"},
    "świdnica": {"lat": 50.8456, "lon": 16.4900, "elev": 280, "postal": "58-100"},
    "świdnik": {"lat": 51.2211, "lon": 22.6969, "elev": 190, "postal": "21-040"},
    "świętochłowice": {"lat": 50.2947, "lon": 18.9153, "elev": 280, "postal": "41-600"},
    "świnoujście": {"lat": 53.9106, "lon": 14.2478, "elev": 5, "postal": "72-600"},
    "szamotuły": {"lat": 52.6111, "lon": 16.5806, "elev": 65, "postal": "64-500"},
    "szczecinek": {"lat": 53.7072, "lon": 16.6992, "elev": 135, "postal": "78-400"},
    "szczytno": {"lat": 53.5619, "lon": 20.9853, "elev": 140, "postal": "12-100"},
    "sztum": {"lat": 53.9244, "lon": 19.0342, "elev": 15, "postal": "82-400"},
    "szubin": {"lat": 52.9869, "lon": 17.7361, "elev": 65, "postal": "89-200"},

    # T
    "tarnobrzeg": {"lat": 50.5728, "lon": 21.6792, "elev": 150, "postal": "39-400"},
    "tarnogród": {"lat": 50.3633, "lon": 22.7461, "elev": 230, "postal": "23-420"},
    "tarnowskie góry": {"lat": 50.4458, "lon": 18.8614, "elev": 295, "postal": "42-600"},
    "tarnów": {"lat": 50.0125, "lon": 20.9861, "elev": 210, "postal": "33-100"},
    "tczew": {"lat": 54.0931, "lon": 18.7958, "elev": 15, "postal": "83-110"},
    "terespol": {"lat": 52.0742, "lon": 23.6164, "elev": 140, "postal": "21-550"},
    "tomaszów lubelski": {"lat": 50.4478, "lon": 23.4161, "elev": 275, "postal": "22-600"},
    "tomaszów mazowiecki": {"lat": 51.5308, "lon": 20.0081, "elev": 185, "postal": "97-200"},
    "trzcianka": {"lat": 53.0406, "lon": 16.4528, "elev": 65, "postal": "64-980"},
    "trzebnica": {"lat": 51.3097, "lon": 17.0633, "elev": 145, "postal": "55-100"},
    "tuchola": {"lat": 53.5892, "lon": 17.8575, "elev": 115, "postal": "89-500"},
    "turek": {"lat": 52.0150, "lon": 18.5003, "elev": 110, "postal": "62-700"},
    "tychy": {"lat": 50.1319, "lon": 18.9961, "elev": 245, "postal": "43-100"},

    # U
    "ustka": {"lat": 54.5806, "lon": 16.8614, "elev": 5, "postal": "76-270"},
    "ustroń": {"lat": 49.7181, "lon": 18.8106, "elev": 360, "postal": "43-450"},

    # W
    "wadowice": {"lat": 49.8833, "lon": 19.4931, "elev": 280, "postal": "34-100"},
    "wałbrzych": {"lat": 50.7714, "lon": 16.2844, "elev": 380, "postal": "58-300"},
    "wałcz": {"lat": 53.2742, "lon": 16.4683, "elev": 110, "postal": "78-600"},
    "warka": {"lat": 51.7878, "lon": 21.1931, "elev": 100, "postal": "05-660"},
    "wąbrzeźno": {"lat": 53.2817, "lon": 18.9536, "elev": 70, "postal": "87-200"},
    "wągrówiec": {"lat": 52.8072, "lon": 17.1989, "elev": 80, "postal": "62-100"},
    "węgorzewo": {"lat": 54.2147, "lon": 21.7372, "elev": 125, "postal": "11-600"},
    "węgrów": {"lat": 52.4014, "lon": 22.0131, "elev": 130, "postal": "07-100"},
    "wejherowo": {"lat": 54.6058, "lon": 18.2353, "elev": 30, "postal": "84-200"},
    "wieliczka": {"lat": 49.9872, "lon": 20.0644, "elev": 280, "postal": "32-020"},
    "wieluń": {"lat": 51.2206, "lon": 18.5694, "elev": 200, "postal": "98-300"},
    "wieruszów": {"lat": 51.2947, "lon": 18.1533, "elev": 185, "postal": "98-400"},
    "więcbork": {"lat": 53.5644, "lon": 17.4742, "elev": 130, "postal": "89-410"},
    "wisła": {"lat": 49.6550, "lon": 18.8586, "elev": 440, "postal": "43-460"},
    "witkowo": {"lat": 52.4228, "lon": 17.7778, "elev": 100, "postal": "62-230"},
    "władysławowo": {"lat": 54.7894, "lon": 18.4058, "elev": 5, "postal": "84-120"},
    "włocławek": {"lat": 52.6483, "lon": 19.0678, "elev": 55, "postal": "87-800"},
    "włodawa": {"lat": 51.5494, "lon": 23.5500, "elev": 170, "postal": "22-200"},
    "włoszczowa": {"lat": 50.8539, "lon": 19.9675, "elev": 255, "postal": "29-100"},
    "wodzisław śląski": {"lat": 50.0033, "lon": 18.4631, "elev": 265, "postal": "44-300"},
    "wołomin": {"lat": 52.3453, "lon": 21.2408, "elev": 95, "postal": "05-200"},
    "wołów": {"lat": 51.3406, "lon": 16.6383, "elev": 110, "postal": "56-100"},
    "wronki": {"lat": 52.7089, "lon": 16.3806, "elev": 55, "postal": "64-510"},
    "września": {"lat": 52.3250, "lon": 17.5650, "elev": 85, "postal": "62-300"},
    "wschowa": {"lat": 51.8017, "lon": 16.3136, "elev": 95, "postal": "67-400"},
    "wysokie mazowieckie": {"lat": 52.9225, "lon": 22.5192, "elev": 145, "postal": "18-200"},
    "wyszków": {"lat": 52.5939, "lon": 21.4614, "elev": 95, "postal": "07-200"},

    # Z
    "zabrze": {"lat": 50.3100, "lon": 18.7856, "elev": 265, "postal": "41-800"},
    "zakopane": {"lat": 49.2992, "lon": 19.9494, "elev": 850, "postal": "34-500"},
    "zambrów": {"lat": 52.9869, "lon": 22.2475, "elev": 140, "postal": "18-300"},
    "zamość": {"lat": 50.7231, "lon": 23.2519, "elev": 220, "postal": "22-400"},
    "zawiercie": {"lat": 50.4900, "lon": 19.4194, "elev": 350, "postal": "42-400"},
    "ząbkowice śląskie": {"lat": 50.5900, "lon": 16.8114, "elev": 295, "postal": "57-200"},
    "zduńska wola": {"lat": 51.5992, "lon": 18.9356, "elev": 175, "postal": "98-220"},
    "zgierz": {"lat": 51.8550, "lon": 19.4064, "elev": 195, "postal": "95-100"},
    "zgorzelec": {"lat": 51.1536, "lon": 15.0106, "elev": 205, "postal": "59-900"},
    "zielona góra": {"lat": 51.9356, "lon": 15.5062, "elev": 80, "postal": "65-001"},
    "złotoryja": {"lat": 51.1264, "lon": 15.9183, "elev": 225, "postal": "59-500"},
    "złotów": {"lat": 53.3619, "lon": 17.0403, "elev": 105, "postal": "77-400"},
    "żagań": {"lat": 51.6167, "lon": 15.3186, "elev": 105, "postal": "68-100"},
    "żary": {"lat": 51.6417, "lon": 15.1381, "elev": 110, "postal": "68-200"},
    "żnin": {"lat": 52.8497, "lon": 17.7156, "elev": 90, "postal": "88-400"},
    "żory": {"lat": 50.0439, "lon": 18.7014, "elev": 255, "postal": "44-240"},
    "żuromin": {"lat": 53.0700, "lon": 19.9111, "elev": 120, "postal": "09-300"},
    "żyrardów": {"lat": 52.0489, "lon": 20.4456, "elev": 100, "postal": "96-300"},
    "żywiec": {"lat": 49.6858, "lon": 19.1925, "elev": 360, "postal": "34-300"},
}

# Merge voivodeship capitals into localities
for city, data in VOIVODESHIP_CAPITALS.items():
    if city not in POLISH_LOCALITIES:
        POLISH_LOCALITIES[city] = {
            "lat": data["lat"],
            "lon": data["lon"],
            "elev": data["elev"],
            "postal": data["postal"]
        }

# ============================================
# POSTAL CODE TO CITY MAPPING
# For reverse lookup from postal code to city
# ============================================
POSTAL_CODE_TO_CITY = {}

# Build reverse index
for city, data in POLISH_LOCALITIES.items():
    postal = data.get("postal", "")
    if postal and postal not in POSTAL_CODE_TO_CITY:
        POSTAL_CODE_TO_CITY[postal] = {
            "city": city.title(),
            "lat": data["lat"],
            "lon": data["lon"],
            "elev": data["elev"]
        }

# Add alternative names (without Polish characters)
ALTERNATIVE_NAMES = {
    "krakow": "kraków",
    "lodz": "łódź",
    "wroclaw": "wrocław",
    "poznan": "poznań",
    "gdansk": "gdańsk",
    "bialystok": "białystok",
    "czestochowa": "częstochowa",
    "torun": "toruń",
    "rzeszow": "rzeszów",
    "gorzow": "gorzów wielkopolski",
    "gorzow wielkopolski": "gorzów wielkopolski",
    "zielona gora": "zielona góra",
    "bielsko biala": "bielsko-biała",
    "jastrzebie zdroj": "jastrzębie-zdrój",
    "jelenia gora": "jelenia góra",
    "piotrkow trybunalski": "piotrków trybunalski",
    "swidnica": "świdnica",
    "swidnik": "świdnik",
    "swinoujscie": "świnoujście",
    "swiecie": "świecie",
    "lomza": "łomża",
    "lowicz": "łowicz",
    "lancut": "łańcut",
    "lask": "łask",
    "leczna": "łęczna",
    "leczyca": "łęczyca",
    "lobez": "łobez",
    "lukow": "łuków",
    "zabkowice slaskie": "ząbkowice śląskie",
    "zywiec": "żywiec",
    "zory": "żory",
    "zary": "żary",
    "zagan": "żagań",
    "znin": "żnin",
    "zuromin": "żuromin",
    "zyrardow": "żyrardów",
}

def lookup_city(city_name: str) -> dict | None:
    """
    Look up a Polish city by name.
    Supports both Polish characters and ASCII equivalents.
    Returns dict with lat, lon, elev, postal or None if not found.
    """
    if not city_name:
        return None

    normalized = city_name.lower().strip()

    # Check direct match
    if normalized in POLISH_LOCALITIES:
        data = POLISH_LOCALITIES[normalized]
        return {
            "city": city_name.title(),
            "lat": data["lat"],
            "lon": data["lon"],
            "elev": data["elev"],
            "postal": data.get("postal", "")
        }

    # Check alternative names (without Polish chars)
    if normalized in ALTERNATIVE_NAMES:
        canonical = ALTERNATIVE_NAMES[normalized]
        if canonical in POLISH_LOCALITIES:
            data = POLISH_LOCALITIES[canonical]
            return {
                "city": canonical.title(),
                "lat": data["lat"],
                "lon": data["lon"],
                "elev": data["elev"],
                "postal": data.get("postal", "")
            }

    # Partial match - find cities starting with the query
    matches = [
        (name, data) for name, data in POLISH_LOCALITIES.items()
        if name.startswith(normalized) or normalized in name
    ]

    if matches:
        # Return first match
        name, data = matches[0]
        return {
            "city": name.title(),
            "lat": data["lat"],
            "lon": data["lon"],
            "elev": data["elev"],
            "postal": data.get("postal", "")
        }

    return None


def lookup_postal_code(postal_code: str) -> dict | None:
    """
    Look up location by Polish postal code (XX-XXX format).
    Returns dict with city, lat, lon, elev or None if not found.
    """
    if not postal_code:
        return None

    # Normalize postal code to XX-XXX format
    digits = ''.join(c for c in postal_code if c.isdigit())
    if len(digits) == 5:
        normalized = f"{digits[:2]}-{digits[2:]}"
    else:
        normalized = postal_code.strip()

    # Direct match
    if normalized in POSTAL_CODE_TO_CITY:
        return POSTAL_CODE_TO_CITY[normalized]

    # Try prefix match (first 2 digits for region)
    prefix = digits[:2] if len(digits) >= 2 else None
    if prefix:
        # Find any postal code starting with this prefix
        for code, data in POSTAL_CODE_TO_CITY.items():
            if code.startswith(prefix):
                return data

    return None


def search_cities(query: str, limit: int = 10) -> list[dict]:
    """
    Search for cities matching query.
    Returns list of matching cities with their data.
    """
    if not query or len(query) < 2:
        return []

    normalized = query.lower().strip()
    results = []

    for name, data in POLISH_LOCALITIES.items():
        if normalized in name or name.startswith(normalized):
            results.append({
                "city": name.title(),
                "lat": data["lat"],
                "lon": data["lon"],
                "elev": data["elev"],
                "postal": data.get("postal", "")
            })
            if len(results) >= limit:
                break

    return results


# Statistics
STATS = {
    "total_localities": len(POLISH_LOCALITIES),
    "voivodeship_capitals": len(VOIVODESHIP_CAPITALS),
    "postal_codes": len(POSTAL_CODE_TO_CITY),
    "alternative_names": len(ALTERNATIVE_NAMES)
}
