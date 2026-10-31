// Places and names for the season formats: the 128-team youth world
// tournament, high schools by state, and college conferences. Player names
// come from a pool that suits the team (a Japanese team gets Japanese names).

// ---- player name pools ----
export const NAME_POOLS = {
    es: {
        first: ['Mateo', 'Santiago', 'Diego', 'Luis', 'Carlos', 'José', 'Juan', 'Miguel', 'Javier', 'Andrés', 'Gabriel', 'Alejandro', 'Daniel', 'Ángel', 'Rafael', 'Emilio', 'Pablo', 'Sebastián', 'Manuel', 'Eduardo', 'Ronald', 'Wilmer', 'Yordan', 'Eloy'],
        last: ['García', 'Rodríguez', 'Martínez', 'Hernández', 'López', 'González', 'Pérez', 'Sánchez', 'Ramírez', 'Torres', 'Flores', 'Rivera', 'Gómez', 'Díaz', 'Reyes', 'Morales', 'Cruz', 'Ortiz', 'Gutiérrez', 'Castillo', 'Vargas', 'Mejía', 'Peña', 'Soto'],
    },
    ja: {
        first: ['Haruto', 'Sota', 'Yuto', 'Riku', 'Kaito', 'Ren', 'Hinata', 'Sora', 'Takumi', 'Daiki', 'Kenta', 'Shota', 'Yuki', 'Ryo', 'Kazuki', 'Hayato', 'Shohei', 'Yu', 'Kota', 'Taiga'],
        last: ['Sato', 'Suzuki', 'Takahashi', 'Tanaka', 'Watanabe', 'Ito', 'Yamamoto', 'Nakamura', 'Kobayashi', 'Kato', 'Yoshida', 'Yamada', 'Sasaki', 'Matsumoto', 'Inoue', 'Kimura', 'Hayashi', 'Shimizu', 'Ono', 'Mori'],
    },
    ko: {
        first: ['Min-jun', 'Seo-jun', 'Do-yun', 'Ha-jun', 'Ji-ho', 'Joon-young', 'Hyun-woo', 'Ji-hoon', 'Seung-min', 'Dong-hyun', 'Jae-won', 'Tae-yang', 'Woo-jin', 'Sung-min', 'Yoon-ho', 'Jun-seo'],
        last: ['Kim', 'Lee', 'Park', 'Choi', 'Jung', 'Kang', 'Cho', 'Yoon', 'Jang', 'Lim', 'Han', 'Oh', 'Seo', 'Shin', 'Kwon', 'Hwang'],
    },
    zh: {
        first: ['Wei', 'Hao', 'Jun', 'Kai', 'Ming', 'Jian', 'Zhi', 'Hong', 'Bo', 'Tao', 'Lei', 'Yang', 'Cheng', 'Wen', 'Jie', 'Yi', 'An', 'Long', 'Yu-cheng', 'Tzu-wei'],
        last: ['Wang', 'Li', 'Zhang', 'Liu', 'Chen', 'Yang', 'Huang', 'Zhao', 'Wu', 'Zhou', 'Xu', 'Sun', 'Lin', 'Lu', 'Kuo', 'Tsai', 'Hsu', 'Chang', 'Ho', 'Cheng'],
    },
    nl: {
        first: ['Daan', 'Sem', 'Lucas', 'Levi', 'Jesse', 'Milan', 'Thijs', 'Bram', 'Ruben', 'Jurickson', 'Xander', 'Didi', 'Kenley', 'Sven', 'Luuk', 'Stijn', 'Niels', 'Joep', 'Ozzie', 'Andruw'],
        last: ['de Jong', 'Jansen', 'de Vries', 'van den Berg', 'van Dijk', 'Bakker', 'Visser', 'Smit', 'Meijer', 'Mulder', 'Bos', 'Vos', 'Hendriks', 'Martina', 'Isenia', 'Balentina', 'Statia', 'Albies', 'Kelly', 'Pieters'],
    },
    it: {
        first: ['Lorenzo', 'Leonardo', 'Francesco', 'Alessandro', 'Mattia', 'Andrea', 'Gabriele', 'Riccardo', 'Tommaso', 'Edoardo', 'Marco', 'Luca', 'Giuseppe', 'Antonio', 'Davide', 'Simone'],
        last: ['Rossi', 'Russo', 'Ferrari', 'Esposito', 'Bianchi', 'Romano', 'Colombo', 'Ricci', 'Marino', 'Greco', 'Bruno', 'Gallo', 'Conti', 'De Luca', 'Costa', 'Giordano'],
    },
    de: {
        first: ['Lukas', 'Leon', 'Finn', 'Jonas', 'Elias', 'Paul', 'Felix', 'Maximilian', 'Noah', 'Ben', 'Luca', 'Tim', 'Jan', 'Niklas', 'Moritz', 'Tobias'],
        last: ['Müller', 'Schmidt', 'Schneider', 'Fischer', 'Weber', 'Meyer', 'Wagner', 'Becker', 'Schulz', 'Hoffmann', 'Koch', 'Bauer', 'Richter', 'Klein', 'Wolf', 'Huber'],
    },
    fr: {
        first: ['Lucas', 'Hugo', 'Louis', 'Gabriel', 'Arthur', 'Jules', 'Nathan', 'Léo', 'Raphaël', 'Théo', 'Mathis', 'Ethan', 'Antoine', 'Félix', 'Samuel', 'Olivier'],
        last: ['Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Richard', 'Petit', 'Durand', 'Leroy', 'Moreau', 'Simon', 'Laurent', 'Lefebvre', 'Tremblay', 'Gagnon', 'Côté'],
    },
    pt: {
        first: ['Miguel', 'Arthur', 'Gael', 'Heitor', 'Theo', 'Davi', 'Gabriel', 'Bernardo', 'Samuel', 'João', 'Pedro', 'Lucas', 'Rafael', 'Thiago', 'Felipe', 'Gustavo'],
        last: ['Silva', 'Santos', 'Oliveira', 'Souza', 'Lima', 'Pereira', 'Ferreira', 'Costa', 'Rodrigues', 'Almeida', 'Nascimento', 'Carvalho', 'Araújo', 'Ribeiro', 'Gomes', 'Barbosa'],
    },
    pl: {
        first: ['Jakub', 'Jan', 'Antoni', 'Szymon', 'Filip', 'Kacper', 'Mikołaj', 'Wojciech', 'Tomáš', 'Ondřej', 'Petr', 'Andriy', 'Oleksandr', 'Dmytro', 'Bohdan', 'Marek'],
        last: ['Nowak', 'Kowalski', 'Wiśniewski', 'Wójcik', 'Kamiński', 'Lewandowski', 'Zieliński', 'Novák', 'Svoboda', 'Dvořák', 'Černý', 'Shevchenko', 'Kovalenko', 'Bondarenko', 'Melnyk', 'Tkachenko'],
    },
    sv: {
        first: ['William', 'Liam', 'Noah', 'Hugo', 'Lucas', 'Oliver', 'Elias', 'Oscar', 'Alexander', 'Axel', 'Erik', 'Gustav', 'Nils', 'Anton', 'Viktor', 'Isak'],
        last: ['Andersson', 'Johansson', 'Karlsson', 'Nilsson', 'Eriksson', 'Larsson', 'Olsson', 'Persson', 'Svensson', 'Gustafsson', 'Pettersson', 'Jonsson', 'Lindberg', 'Lindqvist', 'Berg', 'Holm'],
    },
    he: {
        first: ['Noam', 'Ariel', 'Itai', 'Yonatan', 'Omer', 'Eitan', 'Uri', 'Yosef', 'David', 'Daniel', 'Lior', 'Amit', 'Ido', 'Ben', 'Yair', 'Gal'],
        last: ['Cohen', 'Levi', 'Mizrahi', 'Peretz', 'Biton', 'Dahan', 'Avraham', 'Friedman', 'Azulay', 'Katz', 'Ben-David', 'Shapiro', 'Golan', 'Klein', 'Segal', 'Weiss'],
    },
    af: {
        first: ['Brian', 'Joseph', 'Emmanuel', 'Samuel', 'Daniel', 'Isaac', 'Moses', 'Peter', 'Kwame', 'Kofi', 'Chinedu', 'Emeka', 'Tunde', 'Musa', 'Juma', 'Baraka'],
        last: ['Okello', 'Mugisha', 'Ssempala', 'Kato', 'Otieno', 'Kamau', 'Mwangi', 'Odhiambo', 'Mensah', 'Owusu', 'Boateng', 'Okafor', 'Adeyemi', 'Nwosu', 'Abubakar', 'Wasswa'],
    },
    ar: {
        first: ['Mohammed', 'Ahmed', 'Omar', 'Ali', 'Khalid', 'Faisal', 'Abdullah', 'Yousef', 'Hamad', 'Saud', 'Fahad', 'Ibrahim', 'Tariq', 'Hassan', 'Nasser', 'Rashid'],
        last: ['Al-Harbi', 'Al-Qahtani', 'Al-Ghamdi', 'Al-Zahrani', 'Al-Otaibi', 'Al-Mutairi', 'Al-Dosari', 'Al-Shehri', 'Al-Shammari', 'Al-Anazi', 'Saleh', 'Haddad', 'Khalil', 'Mansour', 'Hamdan', 'Farouk'],
    },
    hi: {
        first: ['Aarav', 'Vivaan', 'Aditya', 'Arjun', 'Rohan', 'Ishaan', 'Kabir', 'Rahul', 'Ali', 'Hamza', 'Bilal', 'Usman', 'Zain', 'Saad', 'Vikram', 'Karan'],
        last: ['Sharma', 'Patel', 'Singh', 'Kumar', 'Gupta', 'Reddy', 'Iyer', 'Khan', 'Malik', 'Hussain', 'Ahmed', 'Qureshi', 'Chaudhry', 'Joshi', 'Mehta', 'Nair'],
    },
    th: {
        first: ['Somchai', 'Anan', 'Thanakorn', 'Kittisak', 'Nattapong', 'Pongsakorn', 'Wichai', 'Chaiwat', 'Sarawut', 'Teerapat', 'Phuwadol', 'Krit'],
        last: ['Saetang', 'Srisuk', 'Wongsawat', 'Boonmee', 'Chaiyaporn', 'Kaewkla', 'Suksawat', 'Rattanakorn', 'Phromma', 'Thongdee', 'Sombat', 'Jaidee'],
    },
    vi: {
        first: ['Minh', 'Huy', 'Khang', 'Bao', 'Phuc', 'Anh', 'Tuan', 'Duc', 'Quang', 'Long', 'Nam', 'Hieu'],
        last: ['Nguyen', 'Tran', 'Le', 'Pham', 'Hoang', 'Huynh', 'Phan', 'Vu', 'Vo', 'Dang', 'Bui', 'Do'],
    },
    id: {
        first: ['Budi', 'Agus', 'Rizky', 'Dimas', 'Fajar', 'Arif', 'Bayu', 'Eko', 'Hendra', 'Yoga', 'Andi', 'Rudi'],
        last: ['Santoso', 'Wijaya', 'Saputra', 'Pratama', 'Hidayat', 'Nugroho', 'Kusuma', 'Setiawan', 'Gunawan', 'Purnomo', 'Siregar', 'Harahap'],
    },
    fil: {
        first: ['Juan', 'Jose', 'Mark', 'Miguel', 'Carlo', 'Paolo', 'Rafael', 'Gabriel', 'Angelo', 'Christian', 'Jerome', 'Joshua'],
        last: ['Santos', 'Reyes', 'Cruz', 'Bautista', 'Ocampo', 'Garcia', 'Mendoza', 'Torres', 'Aquino', 'Dela Cruz', 'Villanueva', 'Ramos'],
    },
};

// ---- youth world tournament: 64 US regions and 64 international ----
// [name, abbr, name pool (default English)]
export const YOUTH_US = [
    ['Alabama', 'AL'], ['Alaska', 'AK'], ['Arizona', 'AZ'], ['Arkansas', 'AR'],
    ['Northern California', 'NCA'], ['Central California', 'CCA'], ['Southern California', 'SCA'],
    ['Colorado', 'CO'], ['Connecticut', 'CT'], ['Delaware', 'DE'], ['District of Columbia', 'DC'],
    ['North Florida', 'FLN'], ['South Florida', 'FLS'], ['Georgia', 'GA'], ['Hawaii', 'HI'], ['Idaho', 'ID'],
    ['Northern Illinois', 'ILN'], ['Southern Illinois', 'ILS'], ['Indiana', 'IN'], ['Iowa', 'IA'], ['Kansas', 'KS'],
    ['Kentucky', 'KY'], ['Louisiana', 'LA'], ['Maine', 'ME'], ['Maryland', 'MD'], ['Massachusetts', 'MA'],
    ['Michigan', 'MI'], ['Minnesota', 'MN'], ['Mississippi', 'MS'], ['Missouri', 'MO'], ['Montana', 'MT'],
    ['Nebraska', 'NE'], ['Nevada', 'NV'], ['New Hampshire', 'NH'], ['New Jersey', 'NJ'], ['New Mexico', 'NM'],
    ['Metro New York', 'NYM'], ['Upstate New York', 'NYU'], ['Eastern North Carolina', 'NCE'], ['Western North Carolina', 'NCW'],
    ['North Dakota', 'ND'], ['Northern Ohio', 'OHN'], ['Southern Ohio', 'OHS'], ['Oklahoma', 'OK'], ['Oregon', 'OR'],
    ['Eastern Pennsylvania', 'PAE'], ['Western Pennsylvania', 'PAW'], ['Rhode Island', 'RI'], ['South Carolina', 'SC'],
    ['South Dakota', 'SD'], ['Tennessee', 'TN'], ['North Texas', 'TXN'], ['South Texas', 'TXS'], ['West Texas', 'TXW'],
    ['Utah', 'UT'], ['Vermont', 'VT'], ['Virginia', 'VA'], ['Washington', 'WA'], ['West Virginia', 'WV'],
    ['Wisconsin', 'WI'], ['Wyoming', 'WY'], ['Puerto Rico', 'PR', 'es'], ['Guam', 'GU', 'fil'], ['U.S. Virgin Islands', 'VI'],
];

export const YOUTH_INTL = [
    ['Japan East', 'JPE', 'ja'], ['Japan West', 'JPW', 'ja'], ['Chinese Taipei', 'TPE', 'zh'], ['South Korea', 'KOR', 'ko'],
    ['China', 'CHN', 'zh'], ['Hong Kong', 'HKG', 'zh'], ['Philippines', 'PHI', 'fil'], ['Indonesia', 'INA', 'id'],
    ['Australia East', 'AUE'], ['Australia West', 'AUW'], ['New Zealand', 'NZL'], ['Thailand', 'THA', 'th'],
    ['Vietnam', 'VIE', 'vi'], ['India', 'IND', 'hi'], ['Pakistan', 'PAK', 'hi'], ['Saudi Arabia', 'KSA', 'ar'],
    ['United Arab Emirates', 'UAE', 'ar'], ['Israel', 'ISR', 'he'],
    ['Canada West', 'CAW'], ['Ontario', 'ONT'], ['Quebec', 'QUE', 'fr'], ['Atlantic Canada', 'CAA'], ['Canadian Prairies', 'CAP'],
    ['Mexico North', 'MXN', 'es'], ['Mexico South', 'MXS', 'es'], ['Cuba', 'CUB', 'es'], ['Dominican Republic', 'DOM', 'es'],
    ['Venezuela', 'VEN', 'es'], ['Colombia', 'COL', 'es'], ['Panama', 'PAN', 'es'], ['Nicaragua', 'NIC', 'es'],
    ['Curaçao', 'CUW', 'nl'], ['Aruba', 'ARU', 'nl'], ['Bahamas', 'BAH'], ['Jamaica', 'JAM'], ['Brazil', 'BRA', 'pt'],
    ['Argentina', 'ARG', 'es'], ['Peru', 'PER', 'es'], ['Guatemala', 'GUA', 'es'], ['Honduras', 'HON', 'es'],
    ['El Salvador', 'ESA', 'es'], ['Costa Rica', 'CRC', 'es'], ['Ecuador', 'ECU', 'es'], ['Uruguay', 'URU', 'es'], ['Chile', 'CHI', 'es'],
    ['Netherlands', 'NED', 'nl'], ['Italy', 'ITA', 'it'], ['Germany', 'GER', 'de'], ['Czechia', 'CZE', 'pl'],
    ['Spain', 'ESP', 'es'], ['Great Britain', 'GBR'], ['France', 'FRA', 'fr'], ['Belgium', 'BEL', 'nl'],
    ['Poland', 'POL', 'pl'], ['Austria', 'AUT', 'de'], ['Switzerland', 'SUI', 'de'], ['Sweden', 'SWE', 'sv'],
    ['Ukraine', 'UKR', 'pl'], ['Ireland', 'IRL'],
    ['Uganda', 'UGA', 'af'], ['Kenya', 'KEN', 'af'], ['South Africa', 'RSA'], ['Nigeria', 'NGR', 'af'], ['Ghana', 'GHA', 'af'],
];

// ---- high school: the 16 biggest cities in each state ----
export const STATES = {
    AL: ['Alabama', 'Huntsville, Birmingham, Montgomery, Mobile, Tuscaloosa, Hoover, Auburn, Dothan, Madison, Decatur, Vestavia Hills, Florence, Gadsden, Prattville, Phenix City, Alabaster'],
    AK: ['Alaska', 'Anchorage, Fairbanks, Juneau, Wasilla, Sitka, Ketchikan, Kenai, Kodiak, Bethel, Palmer, Homer, Soldotna, Valdez, Nome, Utqiagvik, Seward'],
    AZ: ['Arizona', 'Phoenix, Tucson, Mesa, Chandler, Gilbert, Glendale, Scottsdale, Peoria, Tempe, Surprise, Goodyear, Buckeye, Yuma, Avondale, Flagstaff, Queen Creek'],
    AR: ['Arkansas', 'Little Rock, Fayetteville, Fort Smith, Springdale, Jonesboro, Rogers, Conway, North Little Rock, Bentonville, Pine Bluff, Hot Springs, Benton, Sherwood, Texarkana, Russellville, Bella Vista'],
    CA: ['California', 'Los Angeles, San Diego, San Jose, San Francisco, Fresno, Sacramento, Long Beach, Oakland, Bakersfield, Anaheim, Stockton, Riverside, Irvine, Santa Ana, Chula Vista, Fremont'],
    CO: ['Colorado', 'Denver, Colorado Springs, Aurora, Fort Collins, Lakewood, Thornton, Arvada, Westminster, Pueblo, Greeley, Centennial, Boulder, Longmont, Loveland, Broomfield, Castle Rock'],
    CT: ['Connecticut', 'Bridgeport, Stamford, New Haven, Hartford, Waterbury, Norwalk, Danbury, New Britain, Meriden, Bristol, West Haven, Milford, Middletown, Norwich, Shelton, Torrington'],
    DE: ['Delaware', 'Wilmington, Dover, Newark, Middletown, Bear, Glasgow, Hockessin, Brookside, Smyrna, Milford, Claymont, Pike Creek, Seaford, Georgetown, Elsmere, Lewes'],
    FL: ['Florida', 'Jacksonville, Miami, Tampa, Orlando, St. Petersburg, Hialeah, Port St. Lucie, Cape Coral, Tallahassee, Fort Lauderdale, Pembroke Pines, Hollywood, Gainesville, Miramar, Coral Springs, Palm Bay'],
    GA: ['Georgia', 'Atlanta, Columbus, Augusta, Macon, Savannah, Athens, South Fulton, Sandy Springs, Roswell, Johns Creek, Warner Robins, Albany, Alpharetta, Marietta, Stonecrest, Valdosta'],
    HI: ['Hawaii', 'Honolulu, Hilo, Kailua, Kapolei, Kaneohe, Mililani, Ewa Beach, Pearl City, Waipahu, Kahului, Kihei, Makakilo, Wahiawa, Kailua-Kona, Lahaina, Waianae'],
    ID: ['Idaho', "Boise, Meridian, Nampa, Idaho Falls, Caldwell, Pocatello, Coeur d'Alene, Twin Falls, Post Falls, Lewiston, Rexburg, Eagle, Kuna, Ammon, Chubbuck, Mountain Home"],
    IL: ['Illinois', 'Chicago, Aurora, Joliet, Naperville, Rockford, Springfield, Elgin, Peoria, Champaign, Waukegan, Cicero, Bloomington, Arlington Heights, Evanston, Schaumburg, Decatur'],
    IN: ['Indiana', 'Indianapolis, Fort Wayne, Evansville, South Bend, Carmel, Fishers, Bloomington, Hammond, Gary, Lafayette, Muncie, Noblesville, Terre Haute, Kokomo, Anderson, Greenwood'],
    IA: ['Iowa', 'Des Moines, Cedar Rapids, Davenport, Sioux City, Iowa City, Ankeny, West Des Moines, Ames, Waterloo, Council Bluffs, Dubuque, Urbandale, Cedar Falls, Marion, Bettendorf, Mason City'],
    KS: ['Kansas', 'Wichita, Overland Park, Kansas City, Olathe, Topeka, Lawrence, Shawnee, Lenexa, Manhattan, Salina, Hutchinson, Leavenworth, Leawood, Dodge City, Garden City, Emporia'],
    KY: ['Kentucky', 'Louisville, Lexington, Bowling Green, Owensboro, Covington, Georgetown, Richmond, Florence, Hopkinsville, Nicholasville, Elizabethtown, Henderson, Frankfort, Independence, Jeffersontown, Paducah'],
    LA: ['Louisiana', 'New Orleans, Baton Rouge, Shreveport, Lafayette, Lake Charles, Kenner, Bossier City, Monroe, Alexandria, Houma, Slidell, Central, Ruston, Hammond, Sulphur, Natchitoches'],
    ME: ['Maine', 'Portland, Lewiston, Bangor, South Portland, Auburn, Biddeford, Sanford, Saco, Westbrook, Augusta, Waterville, Brunswick, Scarborough, Windham, Gorham, Presque Isle'],
    MD: ['Maryland', 'Baltimore, Columbia, Germantown, Silver Spring, Waldorf, Frederick, Ellicott City, Glen Burnie, Gaithersburg, Rockville, Bethesda, Dundalk, Towson, Bowie, Hagerstown, Annapolis'],
    MA: ['Massachusetts', 'Boston, Worcester, Springfield, Cambridge, Lowell, Brockton, Quincy, Lynn, New Bedford, Fall River, Newton, Lawrence, Somerville, Framingham, Haverhill, Waltham'],
    MI: ['Michigan', 'Detroit, Grand Rapids, Warren, Sterling Heights, Ann Arbor, Lansing, Dearborn, Clinton Township, Canton, Livonia, Troy, Westland, Farmington Hills, Flint, Kalamazoo, Wyoming'],
    MN: ['Minnesota', 'Minneapolis, St. Paul, Rochester, Duluth, Bloomington, Brooklyn Park, Plymouth, Woodbury, Maple Grove, St. Cloud, Lakeville, Blaine, Eagan, Burnsville, Eden Prairie, Coon Rapids'],
    MS: ['Mississippi', 'Jackson, Gulfport, Southaven, Biloxi, Hattiesburg, Olive Branch, Tupelo, Meridian, Greenville, Madison, Clinton, Pearl, Horn Lake, Oxford, Brandon, Starkville'],
    MO: ['Missouri', "Kansas City, St. Louis, Springfield, Columbia, Independence, Lee's Summit, O'Fallon, St. Joseph, St. Charles, Blue Springs, St. Peters, Florissant, Joplin, Chesterfield, Jefferson City, Cape Girardeau"],
    MT: ['Montana', 'Billings, Missoula, Great Falls, Bozeman, Butte, Helena, Kalispell, Havre, Anaconda, Miles City, Belgrade, Livingston, Laurel, Whitefish, Lewistown, Sidney'],
    NE: ['Nebraska', 'Omaha, Lincoln, Bellevue, Grand Island, Kearney, Fremont, Hastings, Norfolk, North Platte, Papillion, Columbus, La Vista, Scottsbluff, South Sioux City, Beatrice, Lexington'],
    NV: ['Nevada', 'Las Vegas, Henderson, Reno, North Las Vegas, Sparks, Carson City, Pahrump, Fernley, Elko, Mesquite, Boulder City, Fallon, Winnemucca, Dayton, Spring Creek, Ely'],
    NH: ['New Hampshire', 'Manchester, Nashua, Concord, Derry, Dover, Rochester, Salem, Merrimack, Hudson, Londonderry, Keene, Bedford, Portsmouth, Goffstown, Laconia, Hampton'],
    NJ: ['New Jersey', 'Newark, Jersey City, Paterson, Elizabeth, Lakewood, Edison, Woodbridge, Toms River, Hamilton, Trenton, Clifton, Camden, Brick, Cherry Hill, Passaic, Union City'],
    NM: ['New Mexico', 'Albuquerque, Las Cruces, Rio Rancho, Santa Fe, Roswell, Farmington, Hobbs, Clovis, Carlsbad, Alamogordo, Gallup, Los Lunas, Deming, Sunland Park, Las Vegas, Portales'],
    NY: ['New York', 'Brooklyn, Queens, Manhattan, The Bronx, Staten Island, Buffalo, Yonkers, Rochester, Syracuse, Albany, New Rochelle, Mount Vernon, Schenectady, Utica, White Plains, Hempstead'],
    NC: ['North Carolina', 'Charlotte, Raleigh, Greensboro, Durham, Winston-Salem, Fayetteville, Cary, Wilmington, High Point, Concord, Asheville, Greenville, Gastonia, Jacksonville, Apex, Chapel Hill'],
    ND: ['North Dakota', 'Fargo, Bismarck, Grand Forks, Minot, West Fargo, Williston, Dickinson, Mandan, Jamestown, Wahpeton, Devils Lake, Watford City, Valley City, Grafton, Lincoln, Beulah'],
    OH: ['Ohio', 'Columbus, Cleveland, Cincinnati, Toledo, Akron, Dayton, Parma, Canton, Youngstown, Lorain, Hamilton, Springfield, Kettering, Elyria, Lakewood, Cuyahoga Falls'],
    OK: ['Oklahoma', 'Oklahoma City, Tulsa, Norman, Broken Arrow, Edmond, Lawton, Moore, Midwest City, Enid, Stillwater, Owasso, Muskogee, Bartlesville, Shawnee, Yukon, Bixby'],
    OR: ['Oregon', 'Portland, Eugene, Salem, Gresham, Hillsboro, Bend, Beaverton, Medford, Springfield, Corvallis, Albany, Tigard, Lake Oswego, Grants Pass, Keizer, Redmond'],
    PA: ['Pennsylvania', 'Philadelphia, Pittsburgh, Allentown, Reading, Erie, Scranton, Bethlehem, Lancaster, Harrisburg, Altoona, York, State College, Wilkes-Barre, Chester, Norristown, Easton'],
    RI: ['Rhode Island', 'Providence, Warwick, Cranston, Pawtucket, East Providence, Woonsocket, Cumberland, Coventry, North Providence, South Kingstown, West Warwick, Johnston, North Kingstown, Newport, Bristol, Westerly'],
    SC: ['South Carolina', 'Charleston, Columbia, North Charleston, Mount Pleasant, Rock Hill, Greenville, Summerville, Goose Creek, Sumter, Hilton Head Island, Florence, Spartanburg, Myrtle Beach, Greer, Aiken, Anderson'],
    SD: ['South Dakota', 'Sioux Falls, Rapid City, Aberdeen, Brookings, Watertown, Mitchell, Yankton, Pierre, Huron, Spearfish, Vermillion, Brandon, Box Elder, Sturgis, Madison, Belle Fourche'],
    TN: ['Tennessee', 'Nashville, Memphis, Knoxville, Chattanooga, Clarksville, Murfreesboro, Franklin, Johnson City, Jackson, Hendersonville, Bartlett, Kingsport, Collierville, Smyrna, Cleveland, Brentwood'],
    TX: ['Texas', 'Houston, San Antonio, Dallas, Austin, Fort Worth, El Paso, Arlington, Corpus Christi, Plano, Lubbock, Laredo, Irving, Garland, Frisco, McKinney, Amarillo'],
    UT: ['Utah', 'Salt Lake City, West Valley City, West Jordan, Provo, St. George, Orem, Sandy, Ogden, Lehi, South Jordan, Layton, Herriman, Taylorsville, Millcreek, Logan, Murray'],
    VT: ['Vermont', 'Burlington, South Burlington, Rutland, Essex Junction, Barre, Montpelier, Winooski, St. Albans, Newport, Vergennes, Brattleboro, Bennington, Colchester, Milton, Middlebury, Springfield'],
    VA: ['Virginia', 'Virginia Beach, Chesapeake, Norfolk, Arlington, Richmond, Newport News, Alexandria, Hampton, Roanoke, Portsmouth, Suffolk, Lynchburg, Harrisonburg, Leesburg, Charlottesville, Blacksburg'],
    WA: ['Washington', 'Seattle, Spokane, Tacoma, Vancouver, Bellevue, Kent, Everett, Renton, Spokane Valley, Federal Way, Yakima, Kirkland, Bellingham, Auburn, Kennewick, Pasco'],
    WV: ['West Virginia', 'Charleston, Huntington, Morgantown, Parkersburg, Wheeling, Weirton, Fairmont, Martinsburg, Beckley, Clarksburg, South Charleston, St. Albans, Vienna, Bluefield, Moundsville, Bridgeport'],
    WI: ['Wisconsin', 'Milwaukee, Madison, Green Bay, Kenosha, Racine, Appleton, Waukesha, Eau Claire, Oshkosh, Janesville, West Allis, La Crosse, Sheboygan, Wauwatosa, Fond du Lac, Wausau'],
    WY: ['Wyoming', 'Cheyenne, Casper, Gillette, Laramie, Rock Springs, Sheridan, Green River, Evanston, Riverton, Jackson, Cody, Rawlins, Lander, Torrington, Douglas, Powell'],
};

export const HS_MASCOTS = [
    'Eagles', 'Tigers', 'Bulldogs', 'Wildcats', 'Panthers', 'Lions', 'Warriors', 'Knights', 'Falcons', 'Hawks',
    'Rams', 'Mustangs', 'Cougars', 'Trojans', 'Spartans', 'Vikings', 'Raiders', 'Bears', 'Patriots', 'Hornets',
    'Pirates', 'Rebels', 'Chargers', 'Titans', 'Owls', 'Bobcats', 'Wolverines', 'Cardinals', 'Jaguars', 'Broncos',
    'Huskies', 'Golden Bears', 'Red Devils', 'Blue Devils', 'Pioneers', 'Generals', 'Saints', 'Comets', 'Rockets', 'Thunder',
];

// ---- college: 8 regional conferences of 8 ----
// [name, abbr, mascot]
export const COLLEGE_CONFERENCES = [
    { name: 'Pacific Coast', abbr: 'PAC', teams: [
        ['Washington', 'WASH', 'Rainmakers'], ['Washington State', 'WSU', 'Orchardmen'], ['Oregon', 'ORE', 'Ospreys'], ['Oregon State', 'OSU', 'Timbermen'],
        ['California', 'CAL', 'Golden Coast'], ['Cal State', 'CSU', 'Condors'], ['Hawaii', 'HAW', 'Surf'], ['Alaska', 'ALAS', 'Glaciers'],
    ] },
    { name: 'Mountain West', abbr: 'MTN', teams: [
        ['Arizona', 'ARIZ', 'Saguaros'], ['Arizona State', 'ASU', 'Scorpions'], ['Utah', 'UTAH', 'Peaks'], ['Utah State', 'USU', 'Arches'],
        ['Colorado', 'COLO', 'Summit'], ['Colorado State', 'CSTU', 'Bighorns'], ['Nevada', 'NEV', 'Silver Miners'], ['New Mexico', 'UNM', 'Roadrunners'],
    ] },
    { name: 'Great Plains', abbr: 'GPC', teams: [
        ['Kansas', 'KAN', 'Sunflowers'], ['Kansas State', 'KSU', 'Wheat Kings'], ['Nebraska', 'NEB', 'Plainsmen'], ['Oklahoma', 'OKLA', 'Red Earth'],
        ['Oklahoma State', 'OKST', 'Wranglers'], ['Iowa', 'IOWA', 'Harvesters'], ['Iowa State', 'ISU', 'Twisters'], ['Missouri', 'MIZ', 'Riverboats'],
    ] },
    { name: 'Great Lakes', abbr: 'GLC', teams: [
        ['Michigan', 'MICH', 'Mariners'], ['Michigan State', 'MSU', 'Lakers'], ['Ohio', 'OHIO', 'Voyagers'], ['Ohio State', 'OHST', 'Ironmen'],
        ['Indiana', 'IND', 'Limestone'], ['Illinois', 'ILL', 'Prairie Fire'], ['Wisconsin', 'WIS', 'Northwoods'], ['Minnesota', 'MINN', 'Loons'],
    ] },
    { name: 'Southeastern', abbr: 'SEC', teams: [
        ['Florida', 'FLA', 'Sharks'], ['Florida State', 'FSU', 'Sunrays'], ['Georgia', 'UGA', 'Peaches'], ['South Carolina', 'SCAR', 'Palmettos'],
        ['Alabama', 'BAMA', 'Ironworks'], ['Tennessee', 'TENN', 'Smokies'], ['Kentucky', 'UK', 'Bluegrass'], ['Mississippi', 'MISS', 'River Kings'],
    ] },
    { name: 'Gulf South', abbr: 'GSC', teams: [
        ['Texas', 'TEX', 'Lone Stars'], ['Texas State', 'TXST', 'Armadillos'], ['North Texas', 'UNT', 'Prairie Dogs'], ['South Texas', 'STX', 'Coyotes'],
        ['Louisiana', 'LOU', 'Bayou Cats'], ['Arkansas', 'ARK', 'Ozarks'], ['Arkansas State', 'ARST', 'Copperheads'], ['Mississippi State', 'MSST', 'Delta Dogs'],
    ] },
    { name: 'Atlantic', abbr: 'ATL', teams: [
        ['North Carolina', 'UNC', 'Pines'], ['North Carolina State', 'NCST', 'Thunderbolts'], ['Virginia', 'UVA', 'Statesmen'], ['West Virginia', 'WVU', 'Coal Miners'],
        ['Maryland', 'MD', 'Crabbers'], ['Delaware', 'DEL', 'First Staters'], ['Pennsylvania', 'PENN', 'Keystones'], ['Pennsylvania State', 'PSU', 'Ridgerunners'],
    ] },
    { name: 'Northeast', abbr: 'NEC', teams: [
        ['New York', 'NY', 'Empire'], ['New Jersey', 'NJ', 'Shore Hawks'], ['Connecticut', 'CONN', 'Nutmeggers'], ['Massachusetts', 'MASS', 'Clippers'],
        ['Rhode Island', 'URI', 'Anchors'], ['Vermont', 'UVM', 'Maples'], ['New Hampshire', 'UNH', 'Granite'], ['Maine', 'MAINE', 'Lobstermen'],
    ] },
];

const PALETTE = ['#1f6feb', '#c2410c', '#2f855a', '#7c3aed', '#be123c', '#0e7490', '#b45309', '#64748b', '#d97706', '#0f766e', '#7f1d1d', '#4338ca', '#15803d', '#9d174d', '#1e3a8a', '#a16207'];
export const paletteColor = (i) => PALETTE[i % PALETTE.length];

// A short, unique abbreviation for a place name.
export function abbreviate(name, used) {
    const words = name.replace(/[^A-Za-z ]/g, ' ').split(/\s+/).filter(Boolean);
    const candidates = [
        words.length > 1 ? words.map((w) => w[0]).join('').slice(0, 3) : null,
        name.replace(/[^A-Za-z]/g, '').slice(0, 3),
        words.length > 1 ? (words[0].slice(0, 2) + words[1][0]) : null,
        words[0].slice(0, 2) + (words[1]?.[0] ?? words[0][2] ?? 'X'),
    ].filter(Boolean).map((s) => s.toUpperCase());
    for (const c of candidates) if (!used.has(c)) { used.add(c); return c; }
    for (let i = 2; ; i++) { const c = candidates[0].slice(0, 2) + i; if (!used.has(c)) { used.add(c); return c; } }
}
