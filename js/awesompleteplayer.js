/**
 * Simple, lightweight, usable local autocomplete library for modern browsers
 * Because there weren’t enough autocomplete scripts in the world? Because I’m completely insane and have NIH syndrome? Probably both. :P
 * @author Lea Verou http://leaverou.github.io/awesomplete
 * MIT license
 */

(function () {

var _ = function (input, o, players) {
	var me = this;

    // Keep track of number of instances for unique IDs
    _.count = (_.count || 0) + 1;
    this.count = _.count;

	// Setup

	this.isOpened = false;

	this.input = $(input);
	this.input.setAttribute("autocomplete", "off");
	this.input.setAttribute("aria-expanded", "false");
	this.input.setAttribute("aria-owns", "awesomplete_list_" + this.count);
	this.input.setAttribute("role", "combobox");

	// store constructor options in case we need to distinguish
	// between default and customized behavior later on
	this.options = o = o || {};

	configure(this, {
		minChars: 2,
		maxItems: 20,
		autoFirst: true,
		data: _.DATA,
		filter: _.FILTER_CONTAINS,
		sort: o.sort === false ? false : _.SORT_BYLENGTH,
		player_sort: _.PLAYER_SORT,
		team_sort: _.TEAM_SORT,
		remove_dups: _.REMOVE_DUPS,
		container: _.CONTAINER,
		item: _.ITEM,
		header: _.HEADER,
		replace: _.REPLACE,
		tabSelect: false
	}, o);

	this.index = -1;

	// Create necessary elements

	this.container = this.container(input);

	this.ul = $.create("ul", {
		hidden: "hidden",
        role: "listbox",
        id: "awesomplete_list_" + this.count,
		inside: this.container
	});

	this.status = $.create("span", {
		className: "visually-hidden",
		role: "status",
		"aria-live": "assertive",
        "aria-atomic": true,
        inside: this.container,
        textContent: this.minChars != 0 ? ("Type " + this.minChars + " or more characters for results.") : "Begin typing for results."
	});

	// Bind events

	this._events = {
		input: {
			"input": this.evaluate.bind(this),
			"blur": this.close.bind(this, { reason: "blur" }),
			"keydown": function(evt) {
				var c = evt.keyCode;

				// If the dropdown `ul` is in view, then act on keydown for the following keys:
				// Enter / Esc / Up / Down
				if(me.opened) {
					if (c === 13 && me.selected) { // Enter
						evt.preventDefault();
						me.select(undefined, undefined, evt);
					}
					else if (c === 9 && me.selected && me.tabSelect) {
						me.select(undefined, undefined, evt);
					}
					else if (c === 27) { // Esc
						me.close({ reason: "esc" });
					}
					else if (c === 38 || c === 40) { // Down/Up arrow
						evt.preventDefault();
						me[c === 38? "previous" : "next"]();
					}
				}
			}
		},
		form: {
			"submit": this.close.bind(this, { reason: "submit" })
		},
		ul: {
			// Prevent the default mousedowm, which ensures the input is not blurred.
			// The actual selection will happen on click. This also ensures dragging the
			// cursor away from the list item will cancel the selection
			"mousedown": function(evt) {
				evt.preventDefault();
			},
			// The click event is fired even if the corresponding mousedown event has called preventDefault
			"click": function(evt) {
				var li = evt.target;

				if (li !== this) {

					while (li && !/li/i.test(li.nodeName)) {
						li = li.parentNode;
					}

					if (li && evt.button === 0) {  // Only select on left click
						evt.preventDefault();
						me.select(li, evt.target, evt);
					}
				}
			}
		}
	};

	$.bind(this.input, this._events.input);
	$.bind(this.input.form, this._events.form);
	$.bind(this.ul, this._events.ul);

	this.suggestions = [];
	this.timeout = null;
	this.list = players || [];


	_.all.push(this);
};

_.prototype = {
	set list(list) {
		
		
		this._list = list;
		
		
		if (2==3) {
			this._stadiums = [{'label': 'Riverside Park (Albany, NY) (1880-1882)', 'value': 'Riverside Park', 'importance': 7}, {'label': 'Columbia Park (Altoona, PA) (1884-1884)', 'value': 'Columbia Park', 'importance': 18}, {'label': 'Angel Stadium of Anaheim -- Edison Field -- Anaheim Stadium (Anaheim, CA) (1966-2016)', 'value': 'Angel Stadium of Anaheim', 'importance': 4079}, {'label': 'Arlington Stadium (Arlington, TX) (1972-1993)', 'value': 'Arlington Stadium', 'importance': 1750}, {'label': 'Rangers Ballpark in Arlington -- The Ballpark in Arlington -- Ameriquest Field (Arlington, TX) (1994-2016)', 'value': 'Rangers Ballpark in Arlington', 'importance': 1838}, {'label': 'Atlanta-Fulton County Stadium (Atlanta, GA) (1966-1996)', 'value': 'Atlanta-Fulton County Stadium', 'importance': 2435}, {'label': 'Turner Field (Atlanta, GA) (1997-2016)', 'value': 'Turner Field', 'importance': 1619}, {'label': 'Madison Avenue Grounds (Baltimore, MD) (1871-1871)', 'value': 'Madison Avenue Grounds', 'importance': 1}, {'label': 'Newington Park (Baltimore, MD) (1872-1882)', 'value': 'Newington Park', 'importance': 112}, {'label': 'Oriole Park I (Baltimore, MD) (1883-1888)', 'value': 'Oriole Park I', 'importance': 352}, {'label': 'Belair Lot (Baltimore, MD) (1884-1884)', 'value': 'Belair Lot', 'importance': 50}, {'label': 'Monumental Park (Baltimore, MD) (1884-1884)', 'value': 'Monumental Park', 'importance': 1}, {'label': 'Oriole Park II (Baltimore, MD) (1889-1891)', 'value': 'Oriole Park II', 'importance': 103}, {'label': 'Oriole Park III (Baltimore, MD) (1891-1899)', 'value': 'Oriole Park III', 'importance': 616}, {'label': 'Oriole Park IV -- American League Park (Baltimore, MD) (1901-1902)', 'value': 'Oriole Park IV', 'importance': 130}, {'label': 'Terrapin Park -- Oriole Park V (Baltimore, MD) (1914-1915)', 'value': 'Terrapin Park', 'importance': 158}, {'label': 'Memorial Stadium (Baltimore, MD) (1954-1991)', 'value': 'Memorial Stadium', 'importance': 3006}, {'label': 'Oriole Park at Camden Yards (Baltimore, MD) (1992-2016)', 'value': 'Oriole Park at Camden Yards', 'importance': 1986}, {'label': 'South End Grounds I -- Walpole Street Grounds (Boston, MA) (1871-1887)', 'value': 'South End Grounds I', 'importance': 685}, {'label': 'Dartmouth Grounds -- Union Park (Boston, MA) (1884-1884)', 'value': 'Dartmouth Grounds', 'importance': 57}, {'label': 'South End Grounds II (Boston, MA) (1888-1894)', 'value': 'South End Grounds II', 'importance': 420}, {'label': 'Congress Street Grounds (Boston, MA) (1890-1894)', 'value': 'Congress Street Grounds', 'importance': 170}, {'label': 'South End Grounds III (Boston, MA) (1894-1914)', 'value': 'South End Grounds III', 'importance': 1489}, {'label': 'Huntington Avenue Baseball Grounds (Boston, MA) (1901-1911)', 'value': 'Huntington Avenue Baseball Grounds', 'importance': 831}, {'label': 'Fenway Park (Boston, MA) (1912-2016)', 'value': 'Fenway Park', 'importance': 8256}, {'label': 'Braves Field -- Bee Hive (Boston, MA) (1915-1952)', 'value': 'Braves Field', 'importance': 2871}, {'label': 'Riverside Grounds (Buffalo, NY) (1879-1883)', 'value': 'Riverside Grounds', 'importance': 212}, {'label': 'Olympic Park I (Buffalo, NY) (1884-1885)', 'value': 'Olympic Park I', 'importance': 108}, {'label': 'Olympic Park II (Buffalo, NY) (1890-1890)', 'value': 'Olympic Park II', 'importance': 65}, {'label': 'International Fair Association Grounds -- Federal League Park (Buffalo, NY) (1914-1915)', 'value': 'International Fair Association Grounds', 'importance': 156}, {'label': 'Mahaffey Park -- Pastime Park (Canton, OH) (1902-1903)', 'value': 'Mahaffey Park', 'importance': 3}, {'label': 'Pastime Park (Canton, OH) (1890-1890)', 'value': 'Pastime Park', 'importance': 1}, {'label': 'Lake Front Park I -- Union Base-ball Grounds (Chicago, IL) (1871-1871)', 'value': 'Lake Front Park I', 'importance': 17}, {'label': '23rd Street Park (Chicago, IL) (1872-1877)', 'value': '23rd Street Park', 'importance': 129}, {'label': 'Lake Front Park II (Chicago, IL) (1878-1884)', 'value': 'Lake Front Park II', 'importance': 314}, {'label': 'South Side Park I -- Cricket Club Grounds -- Union Grounds (Chicago, IL) (1884-1884)', 'value': 'South Side Park I', 'importance': 35}, {'label': 'West Side Park (Chicago, IL) (1885-1891)', 'value': 'West Side Park', 'importance': 429}, {'label': 'South Side Park II (Chicago, IL) (1890-1893)', 'value': 'South Side Park II', 'importance': 181}, {'label': 'West Side Grounds (Chicago, IL) (1893-1915)', 'value': 'West Side Grounds', 'importance': 1739}, {'label': 'South Side Park III (Chicago, IL) (1901-1910)', 'value': 'South Side Park III', 'importance': 718}, {'label': 'Comiskey Park I -- White Sox Park (Chicago, IL) (1910-1990)', 'value': 'Comiskey Park I', 'importance': 6247}, {'label': 'Wrigley Field -- Weeghman Park -- Cubs Park (Chicago, IL) (1914-2016)', 'value': 'Wrigley Field', 'importance': 8114}, {'label': 'U.S. Cellular Field -- White Sox Park -- Comiskey Park II (Chicago, IL) (1991-2016)', 'value': 'U.S. Cellular Field', 'importance': 2074}, {'label': 'Lincoln Park Grounds -- Union Cricket Club Grounds (Cincinnati, OH) (1871-1871)', 'value': 'Lincoln Park Grounds', 'importance': 3}, {'label': 'Avenue Grounds (Cincinnati, OH) (1876-1879)', 'value': 'Avenue Grounds', 'importance': 132}, {'label': 'Bank Street Grounds (Cincinnati, OH) (1880-1884)', 'value': 'Bank Street Grounds', 'importance': 185}, {'label': 'League Park I (Cincinnati, OH) (1884-1893)', 'value': 'League Park I', 'importance': 698}, {'label': 'League Park II (Cincinnati, OH) (1894-1901)', 'value': 'League Park II', 'importance': 577}, {'label': 'Palace of the Fans -- League Park III (Cincinnati, OH) (1902-1911)', 'value': 'Palace of the Fans', 'importance': 779}, {'label': 'Crosley Field -- Redland Field (Cincinnati, OH) (1912-1970)', 'value': 'Crosley Field', 'importance': 4544}, {'label': 'Cinergy Field -- Riverfront Stadium (Cincinnati, OH) (1970-2002)', 'value': 'Cinergy Field', 'importance': 2576}, {'label': 'Great American Ballpark (Cincinnati, OH) (2003-2016)', 'value': 'Great American Ballpark', 'importance': 1134}, {'label': 'National Association Grounds (Cleveland, OH) (1871-1872)', 'value': 'National Association Grounds', 'importance': 16}, {'label': 'League Park I -- Kennard Street Park (Cleveland, OH) (1879-1884)', 'value': 'League Park I', 'importance': 275}, {'label': 'League Park II -- American Association Park (Cleveland, OH) (1887-1890)', 'value': 'League Park II', 'importance': 246}, {'label': 'Brotherhood Park -- Players League Park (Cleveland, OH) (1890-1890)', 'value': 'Brotherhood Park', 'importance': 62}, {'label': 'League Park III -- National League Park III (Cleveland, OH) (1891-1909)', 'value': 'League Park III', 'importance': 1220}, {'label': 'League Park IV -- Dunn Field (Cleveland, OH) (1910-1946)', 'value': 'League Park IV', 'importance': 2376}, {'label': 'Cleveland Stadium -- Municipal Stadium (Cleveland, OH) (1932-1993)', 'value': 'Cleveland Stadium', 'importance': 4196}, {'label': 'Progressive Field -- Jacobs Field (Cleveland, OH) (1994-2016)', 'value': 'Progressive Field', 'importance': 1817}, {'label': 'Cedar Avenue Driving Park (Cleveland, OH) (1887-1887)', 'value': 'Cedar Avenue Driving Park', 'importance': 1}, {'label': 'Euclid Beach Park (Collinwood, OH) (1898-1898)', 'value': 'Euclid Beach Park', 'importance': 2}, {'label': 'Recreation Park I (Columbus, OH) (1883-1884)', 'value': 'Recreation Park I', 'importance': 102}, {'label': 'Recreation Park II (Columbus, OH) (1889-1891)', 'value': 'Recreation Park II', 'importance': 202}, {'label': 'Neil Park I (Columbus, OH) (1902-1903)', 'value': 'Neil Park I', 'importance': 2}, {'label': 'Neil Park II (Columbus, OH) (1905-1905)', 'value': 'Neil Park II', 'importance': 2}, {'label': 'Star Baseball Park (Covington, KY) (1875-1875)', 'value': 'Star Baseball Park', 'importance': 1}, {'label': 'Fairview Park (Dayton, OH) (1902-1902)', 'value': 'Fairview Park', 'importance': 1}, {'label': 'Mile High Stadium (Denver, CO) (1993-1994)', 'value': 'Mile High Stadium', 'importance': 138}, {'label': 'Coors Field (Denver, CO) (1995-2016)', 'value': 'Coors Field', 'importance': 1774}, {'label': 'Recreation Park (Detroit, MI) (1881-1890)', 'value': 'Recreation Park', 'importance': 439}, {'label': 'Bennett Park (Detroit, MI) (1901-1911)', 'value': 'Bennett Park', 'importance': 796}, {'label': 'Burns Park -- West End Park (Detroit, MI) (1901-1902)', 'value': 'Burns Park', 'importance': 23}, {'label': 'Tiger Stadium -- Navin Field -- Briggs Stadium (Detroit, MI) (1912-1999)', 'value': 'Tiger Stadium', 'importance': 6879}, {'label': 'Comerica Park (Detroit, MI) (2000-2016)', 'value': 'Comerica Park', 'importance': 1375}, {'label': 'Fairview Park Fair Grounds (Dover, DE) (1875-1875)', 'value': 'Fairview Park Fair Grounds', 'importance': 1}, {'label': 'Maple Avenue Driving Park (Elmira, NY) (1885-1885)', 'value': 'Maple Avenue Driving Park', 'importance': 2}, {'label': 'Grand Duchess -- Hamilton Field (Fort Wayne, IN) (1871-1871)', 'value': 'Grand Duchess', 'importance': 9}, {'label': 'Jailhouse Flats (Fort Wayne, IN) (1902-1902)', 'value': 'Jailhouse Flats', 'importance': 2}, {'label': 'Fort Bragg Field (Fort Bragg, NC) (2016-2016)', 'value': 'Fort Bragg Field', 'importance': 1}, {'label': 'Geauga Lake Grounds (Geauga Lake, OH) (1888-1888)', 'value': 'Geauga Lake Grounds', 'importance': 3}, {'label': 'Gloucester Point Grounds (Gloucester City, NJ) (1888-1890)', 'value': 'Gloucester Point Grounds', 'importance': 30}, {'label': 'Ramona Park (Grand Rapids, MI) (1903-1903)', 'value': 'Ramona Park', 'importance': 1}, {'label': 'Harrison Field (Harrison, NJ) (1915-1915)', 'value': 'Harrison Field', 'importance': 79}, {'label': 'Aloha Stadium (Honolulu, HI) (1997-1997)', 'value': 'Aloha Stadium', 'importance': 3}, {'label': 'Colt Stadium (Houston, TX) (1962-1964)', 'value': 'Colt Stadium', 'importance': 244}, {'label': 'Astrodome (Houston, TX) (1965-1999)', 'value': 'Astrodome', 'importance': 2774}, {'label': 'Minute Maid Park -- Enron Field -- Astros Field (Houston, TX) (2000-2016)', 'value': 'Minute Maid Park', 'importance': 1374}, {'label': 'Hartford Ball Club Grounds (Hartford, CT) (1874-1876)', 'value': 'Hartford Ball Club Grounds', 'importance': 100}, {'label': 'Hartford Trotting Park (Hartford, CT) (1872-1872)', 'value': 'Hartford Trotting Park', 'importance': 3}, {'label': 'South Street Park (Indianapolis, IN) (1878-1878)', 'value': 'South Street Park', 'importance': 22}, {'label': 'Seventh Street Park I (Indianapolis, IN) (1884-1885)', 'value': 'Seventh Street Park I', 'importance': 45}, {'label': 'Bruce Grounds (Indianapolis, IN) (1884-1884)', 'value': 'Bruce Grounds', 'importance': 11}, {'label': 'Seventh Street Park II (Indianapolis, IN) (1887-1887)', 'value': 'Seventh Street Park II', 'importance': 64}, {'label': 'Seventh Street Park III (Indianapolis, IN) (1888-1889)', 'value': 'Seventh Street Park III', 'importance': 135}, {'label': 'Indianapolis Park (Indianapolis, IN) (1890-1890)', 'value': 'Indianapolis Park', 'importance': 6}, {'label': 'Federal League Park -- Washington Park (Indianapolis, IN) (1914-1914)', 'value': 'Federal League Park', 'importance': 80}, {'label': 'Windsor Beach (Irondequoit, NY) (1890-1890)', 'value': 'Windsor Beach', 'importance': 6}, {'label': 'Oakland Park (Jersey City, NJ) (1889-1889)', 'value': 'Oakland Park', 'importance': 2}, {'label': 'Roosevelt Stadium (Jersey City, NJ) (1956-1957)', 'value': 'Roosevelt Stadium', 'importance': 15}, {'label': 'Athletic Park (Kansas City, MO) (1884-1884)', 'value': 'Athletic Park', 'importance': 36}, {'label': 'Association Park (Kansas City, MO) (1886-1888)', 'value': 'Association Park', 'importance': 114}, {'label': 'Exposition Park (Kansas City, MO) (1888-1892)', 'value': 'Exposition Park', 'importance': 74}, {'label': 'Gordon and Koppel Field (Kansas City, MO) (1914-1915)', 'value': 'Gordon and Koppel Field', 'importance': 151}, {'label': 'Municipal Stadium (Kansas City, MO) (1955-1972)', 'value': 'Municipal Stadium', 'importance': 1348}, {'label': 'Kauffman Stadium -- Royals Stadium (Kansas City, MO) (1973-2016)', 'value': 'Kauffman Stadium', 'importance': 3494}, {'label': "Perry Park -- Walte's Pasture (Keokuk, IA) (1875-1875)", 'value': 'Perry Park', 'importance': 8}, {'label': 'Cashman Field (Las Vegas, NV) (1996-1996)', 'value': 'Cashman Field', 'importance': 6}, {'label': "The Ballpark at Disney's Wide World (Lake Buena Vista, FL) (2007-2008)", 'value': "The Ballpark at Disney's Wide World", 'importance': 6}, {'label': 'Los Angeles Memorial Coliseum (Los Angeles, CA) (1958-1961)', 'value': 'Los Angeles Memorial Coliseum', 'importance': 309}, {'label': 'Wrigley Field (Los Angeles, CA) (1961-1961)', 'value': 'Wrigley Field', 'importance': 82}, {'label': 'Dodger Stadium -- Chavez Ravine (Los Angeles, CA) (1962-2016)', 'value': 'Dodger Stadium', 'importance': 4714}, {'label': 'Louisville Baseball Park (Louisville, KY) (1876-1877)', 'value': 'Louisville Baseball Park', 'importance': 62}, {'label': 'Eclipse Park I (Louisville, KY) (1882-1893)', 'value': 'Eclipse Park I', 'importance': 676}, {'label': 'Eclipse Park II (Louisville, KY) (1893-1899)', 'value': 'Eclipse Park II', 'importance': 435}, {'label': 'Eclipse Park III (Louisville, KY) (1899-1899)', 'value': 'Eclipse Park III', 'importance': 12}, {'label': 'Ludlow Baseball Park (Ludlow, KY) (1875-1875)', 'value': 'Ludlow Baseball Park', 'importance': 1}, {'label': 'Long Island Grounds (Maspeth, NY) (1890-1890)', 'value': 'Long Island Grounds', 'importance': 2}, {'label': 'Sun Life Stadium -- Joe Robbie Stadium -- Pro Player Stadium -- Dolphin Stadium -- LandShark Stadium (Miami, FL) (1993-2011)', 'value': 'Sun Life Stadium', 'importance': 1496}, {'label': 'Marlins Park (Miami, FL) (2012-2016)', 'value': 'Marlins Park', 'importance': 404}, {'label': 'Mansfield Club Grounds (Middletown, CT) (1872-1872)', 'value': 'Mansfield Club Grounds', 'importance': 7}, {'label': 'Milwaukee Base-Ball Grounds (Milwaukee, WI) (1878-1878)', 'value': 'Milwaukee Base-Ball Grounds', 'importance': 25}, {'label': 'Wright Street Grounds (Milwaukee, WI) (1884-1885)', 'value': 'Wright Street Grounds', 'importance': 14}, {'label': 'Athletic Park (Milwaukee, WI) (1891-1891)', 'value': 'Athletic Park', 'importance': 20}, {'label': 'Lloyd Street Grounds (Milwaukee, WI) (1901-1901)', 'value': 'Lloyd Street Grounds', 'importance': 70}, {'label': 'County Stadium (Milwaukee, WI) (1953-2000)', 'value': 'County Stadium', 'importance': 3484}, {'label': 'Miller Park (Milwaukee, WI) (2001-2016)', 'value': 'Miller Park', 'importance': 1301}, {'label': 'Athletic Park (Minneapolis, MN) (1891-1891)', 'value': 'Athletic Park', 'importance': 1}, {'label': 'Metropolitan Stadium (Bloomington, MN) (1961-1981)', 'value': 'Metropolitan Stadium', 'importance': 1674}, {'label': 'Hubert H. Humphrey Metrodome (Minneapolis, MN) (1982-2009)', 'value': 'Hubert H. Humphrey Metrodome', 'importance': 2242}, {'label': 'Target Field (Minneapolis, MN) (2010-2016)', 'value': 'Target Field', 'importance': 567}, {'label': 'Estadio Monterrey (Monterrey, Nuevo Leon) (1996-1999)', 'value': 'Estadio Monterrey', 'importance': 4}, {'label': 'Parc Jarry -- Jarry Park (Montreal, QC) (1969-1976)', 'value': 'Parc Jarry', 'importance': 641}, {'label': 'Stade Olympique -- Olympic Stadium (Montreal, QC) (1977-2004)', 'value': 'Stade Olympique', 'importance': 2145}, {'label': 'Howard Avenue Grounds -- Brewster Park (New Haven, CT) (1875-1877)', 'value': 'Howard Avenue Grounds', 'importance': 27}, {'label': 'Hamilton Park (New Haven, CT) (1875-1875)', 'value': 'Hamilton Park', 'importance': 1}, {'label': "Beyerle's Park -- Forest City Park (Newburgh Township, OH) (1888-1888)", 'value': "Beyerle's Park", 'importance': 1}, {'label': "Wiedenmeyer's Park (Newark, NJ) (1904-1904)", 'value': "Wiedenmeyer's Park", 'importance': 1}, {'label': 'Union Grounds (Brooklyn, NY) (1871-1878)', 'value': 'Union Grounds', 'importance': 315}, {'label': 'Capitoline Grounds (Brooklyn, NY) (1872-1872)', 'value': 'Capitoline Grounds', 'importance': 18}, {'label': 'Polo Grounds I (Southeast Diamond) (New York, NY) (1883-1888)', 'value': 'Polo Grounds I (Southeast Diamond)', 'importance': 472}, {'label': 'Polo Grounds II (Southwest Diamond) (New York, NY) (1883-1883)', 'value': 'Polo Grounds II (Southwest Diamond)', 'importance': 13}, {'label': 'Washington Park I (Brooklyn, NY) (1884-1889)', 'value': 'Washington Park I', 'importance': 290}, {'label': 'Metropolitan Park (New York, NY) (1884-1884)', 'value': 'Metropolitan Park', 'importance': 33}, {'label': "Grauer's Ridgewood Park -- Ridgewood Park I (Queens, NY) (1886-1886)", 'value': "Grauer's Ridgewood Park", 'importance': 14}, {'label': 'Washington Park II (Brooklyn, NY) (1889-1890)', 'value': 'Washington Park II', 'importance': 123}, {'label': 'Polo Grounds III (New York, NY) (1889-1890)', 'value': 'Polo Grounds III', 'importance': 112}, {'label': 'Polo Grounds IV (New York, NY) (1890-1911)', 'value': 'Polo Grounds IV', 'importance': 1545}, {'label': 'Eastern Park (Brooklyn, NY) (1890-1897)', 'value': 'Eastern Park', 'importance': 554}, {'label': 'Washington Park III (Brooklyn, NY) (1898-1912)', 'value': 'Washington Park III', 'importance': 1125}, {'label': 'Hilltop Park (New York, NY) (1903-1912)', 'value': 'Hilltop Park', 'importance': 776}, {'label': 'Polo Grounds V (New York, NY) (1911-1963)', 'value': 'Polo Grounds V', 'importance': 4490}, {'label': 'Ebbets Field (Brooklyn, NY) (1913-1957)', 'value': 'Ebbets Field', 'importance': 3447}, {'label': 'Yankee Stadium I (New York, NY) (1923-2008)', 'value': 'Yankee Stadium I', 'importance': 6581}, {'label': 'Shea Stadium -- William A. Shea Stadium (New York, NY) (1964-2008)', 'value': 'Shea Stadium', 'importance': 3737}, {'label': "Wallace's Ridgewood Park -- Ridgewood Park II (Queens, NY) (1887-1890)", 'value': "Wallace's Ridgewood Park", 'importance': 77}, {'label': 'Washington Park IV (Brooklyn, NY) (1914-1915)', 'value': 'Washington Park IV', 'importance': 154}, {'label': 'Citi Field (New York, NY) (2009-2016)', 'value': 'Citi Field', 'importance': 648}, {'label': 'Yankee Stadium II (New York, NY) (2009-2016)', 'value': 'Yankee Stadium II', 'importance': 648}, {'label': 'Oakland-Alameda County Coliseum -- Network Associates Coliseum (Oakland, CA) (1968-2016)', 'value': 'Oakland-Alameda County Coliseum', 'importance': 3897}, {'label': 'East End Park -- Pendleton Park (Cincinnati, OH) (1891-1891)', 'value': 'East End Park', 'importance': 45}, {'label': 'Jefferson Street Grounds -- Athletics Park (Philadelphia, PA) (1871-1890)', 'value': 'Jefferson Street Grounds', 'importance': 746}, {'label': 'Centennial Park (Philadelphia, PA) (1875-1875)', 'value': 'Centennial Park', 'importance': 8}, {'label': 'Oakdale Park (Philadelphia, PA) (1882-1882)', 'value': 'Oakdale Park', 'importance': 39}, {'label': 'Recreation Park (Philadelphia, PA) (1883-1886)', 'value': 'Recreation Park', 'importance': 224}, {'label': 'Keystone Park (Philadelphia, PA) (1884-1884)', 'value': 'Keystone Park', 'importance': 35}, {'label': 'Huntingdon Grounds I (Philadelphia, PA) (1887-1894)', 'value': 'Huntingdon Grounds I', 'importance': 531}, {'label': 'Forepaugh Park (Philadelphia, PA) (1890-1891)', 'value': 'Forepaugh Park', 'importance': 137}, {'label': 'University of Penn. Athletic Field (Philadelphia, PA) (1894-1894)', 'value': 'University of Penn. Athletic Field', 'importance': 6}, {'label': 'Baker Bowl (Philadelphia, PA) (1895-1938)', 'value': 'Baker Bowl', 'importance': 3218}, {'label': 'Columbia Park (Philadelphia, PA) (1901-1908)', 'value': 'Columbia Park', 'importance': 599}, {'label': 'Shibe Park -- Connie Mack Stadium (Philadelphia, PA) (1909-1970)', 'value': 'Shibe Park', 'importance': 6055}, {'label': 'Veterans Stadium (Philadelphia, PA) (1971-2003)', 'value': 'Veterans Stadium', 'importance': 2617}, {'label': 'Citizens Bank Park (Philadelphia, PA) (2004-2016)', 'value': 'Citizens Bank Park', 'importance': 1056}, {'label': 'Huntingdon Grounds II (Philadelphia, PA) (1894-1894)', 'value': 'Huntingdon Grounds II', 'importance': 22}, {'label': 'Chase Field -- Bank One Ballpark (Phoenix, AZ) (1998-2016)', 'value': 'Chase Field', 'importance': 1537}, {'label': 'Union Park (Pittsburgh, PA) (1878-1878)', 'value': 'Union Park', 'importance': 3}, {'label': 'Exposition Park I -- Lower Field (Pittsburgh, PA) (1882-1883)', 'value': 'Exposition Park I', 'importance': 69}, {'label': 'Exposition Park II -- Upper Field (Pittsburgh, PA) (1883-1884)', 'value': 'Exposition Park II', 'importance': 22}, {'label': 'Recreation Park (Pittsburgh, PA) (1884-1890)', 'value': 'Recreation Park', 'importance': 430}, {'label': 'Exposition Park III (Pittsburgh, PA) (1890-1915)', 'value': 'Exposition Park III', 'importance': 1572}, {'label': 'Forbes Field (Pittsburgh, PA) (1909-1970)', 'value': 'Forbes Field', 'importance': 4760}, {'label': 'Three Rivers Stadium (Pittsburgh, PA) (1970-2000)', 'value': 'Three Rivers Stadium', 'importance': 2407}, {'label': 'PNC Park (Pittsburgh, PA) (2001-2016)', 'value': 'PNC Park', 'importance': 1294}, {'label': 'Adelaide Avenue Grounds (Providence, RI) (1875-1875)', 'value': 'Adelaide Avenue Grounds', 'importance': 2}, {'label': 'Messer Street Grounds (Providence, RI) (1878-1885)', 'value': 'Messer Street Grounds', 'importance': 358}, {'label': 'Agricultural Society Fair Grounds (Rockford, IL) (1871-1871)', 'value': 'Agricultural Society Fair Grounds', 'importance': 6}, {'label': 'Richmond Fair Grounds (Richmond, VA) (1875-1875)', 'value': 'Richmond Fair Grounds', 'importance': 2}, {'label': 'Allens Pasture (Richmond, VA) (1884-1884)', 'value': 'Allens Pasture', 'importance': 22}, {'label': 'Culver Field I (Rochester, NY) (1890-1890)', 'value': 'Culver Field I', 'importance': 57}, {'label': 'Culver Field II (Rochester, NY) (1898-1898)', 'value': 'Culver Field II', 'importance': 2}, {'label': 'Ontario Beach Grounds (Rochester, NY) (1898-1898)', 'value': 'Ontario Beach Grounds', 'importance': 1}, {'label': 'St. George Cricket Grounds (New York, NY) (1886-1889)', 'value': 'St. George Cricket Grounds', 'importance': 148}, {'label': 'Qualcomm Stadium -- San Diego/Jack Murphy Stadium (San Diego, CA) (1969-2003)', 'value': 'Qualcomm Stadium', 'importance': 2768}, {'label': 'PETCO Park (San Diego, CA) (2004-2016)', 'value': 'PETCO Park', 'importance': 1053}, {'label': "Sick's Stadium (Seattle, WA) (1969-1969)", 'value': "Sick's Stadium", 'importance': 82}, {'label': 'Kingdome (Seattle, WA) (1977-1999)', 'value': 'Kingdome', 'importance': 1755}, {'label': 'Safeco Field (Seattle, WA) (1999-2016)', 'value': 'Safeco Field', 'importance': 1424}, {'label': 'Seals Stadium (San Francisco, CA) (1958-1959)', 'value': 'Seals Stadium', 'importance': 154}, {'label': 'Candlestick Park -- 3Com Park (San Francisco, CA) (1960-1999)', 'value': 'Candlestick Park', 'importance': 3173}, {'label': 'AT&T Park -- Pacific Bell Park -- SBC Park (San Francisco, CA) (2000-2016)', 'value': 'AT&T Park', 'importance': 1379}, {'label': 'Estadio Hiram Bithorn (San Juan, ) (2001-2010)', 'value': 'Estadio Hiram Bithorn', 'importance': 47}, {'label': 'Hampden Park Race Track -- Springfield Track (Springfield, MA) (1872-1875)', 'value': 'Hampden Park Race Track', 'importance': 3}, {'label': 'Red Stockings Base Ball Park (St. Louis, MO) (1875-1875)', 'value': 'Red Stockings Base Ball Park', 'importance': 14}, {'label': 'Grand Avenue Park (St. Louis, MO) (1875-1878)', 'value': 'Grand Avenue Park', 'importance': 97}, {'label': "Sportsman's Park I (St. Louis, MO) (1882-1892)", 'value': "Sportsman's Park I", 'importance': 717}, {'label': 'Union Grounds (St. Louis, MO) (1884-1886)', 'value': 'Union Grounds', 'importance': 175}, {'label': 'Robison Field (St. Louis, MO) (1893-1920)', 'value': 'Robison Field', 'importance': 2021}, {'label': "Sportsman's Park II (St. Louis, MO) (1902-1908)", 'value': "Sportsman's Park II", 'importance': 530}, {'label': "Sportsman's Park III -- Busch Stadium I (St. Louis, MO) (1909-1966)", 'value': "Sportsman's Park III", 'importance': 7022}, {'label': "Handlan's Park -- Federal League Park (St. Louis, MO) (1914-1915)", 'value': "Handlan's Park", 'importance': 158}, {'label': 'Busch Stadium II (St. Louis, MO) (1966-2005)', 'value': 'Busch Stadium II', 'importance': 3174}, {'label': 'Busch Stadium III (St. Louis, MO) (2006-2016)', 'value': 'Busch Stadium III', 'importance': 890}, {'label': 'Tropicana Field (St. Petersburg, FL) (1998-2016)', 'value': 'Tropicana Field', 'importance': 1532}, {'label': 'Sydney Cricket Ground (Sydney, New South Wales) (2014-2014)', 'value': 'Sydney Cricket Ground', 'importance': 2}, {'label': 'Star Park I -- Newell Park (Syracuse, NY) (1879-1879)', 'value': 'Star Park I', 'importance': 34}, {'label': 'Star Park II (Syracuse, NY) (1890-1890)', 'value': 'Star Park II', 'importance': 54}, {'label': 'Iron Pier (Syracuse, NY) (1890-1890)', 'value': 'Iron Pier', 'importance': 1}, {'label': 'Three Rivers Park (Three Rivers, NY) (1890-1890)', 'value': 'Three Rivers Park', 'importance': 5}, {'label': 'Tokyo Dome (Tokyo, Tokyo) (2000-2012)', 'value': 'Tokyo Dome', 'importance': 8}, {'label': 'League Park (Toledo, OH) (1884-1884)', 'value': 'League Park', 'importance': 54}, {'label': 'Tri-State Fair Grounds (Toledo, OH) (1884-1884)', 'value': 'Tri-State Fair Grounds', 'importance': 1}, {'label': 'Speranza Park (Toledo, OH) (1890-1890)', 'value': 'Speranza Park', 'importance': 68}, {'label': 'Armory Park (Toledo, OH) (1903-1903)', 'value': 'Armory Park', 'importance': 2}, {'label': 'Exhibition Stadium (Toronto, ON) (1977-1989)', 'value': 'Exhibition Stadium', 'importance': 968}, {'label': 'Rogers Centre -- Skydome (Toronto, ON) (1989-2016)', 'value': 'Rogers Centre', 'importance': 2208}, {'label': "Haymakers' Grounds (Troy, NY) (1871-1881)", 'value': "Haymakers' Grounds", 'importance': 106}, {'label': 'Putnam Grounds (Troy, NY) (1879-1879)', 'value': 'Putnam Grounds', 'importance': 41}, {'label': 'Rocky Point Park (Warwick, RI) (1903-1903)', 'value': 'Rocky Point Park', 'importance': 1}, {'label': 'Olympic Grounds (Washington, DC) (1871-1875)', 'value': 'Olympic Grounds', 'importance': 44}, {'label': 'National Grounds (Washington, DC) (1872-1872)', 'value': 'National Grounds', 'importance': 7}, {'label': 'Capitol Grounds (Washington, DC) (1884-1884)', 'value': 'Capitol Grounds', 'importance': 65}, {'label': 'Athletic Park (Washington, DC) (1884-1884)', 'value': 'Athletic Park', 'importance': 30}, {'label': 'Swampoodle Grounds (Washington, DC) (1886-1889)', 'value': 'Swampoodle Grounds', 'importance': 250}, {'label': 'Boundary Field (Washington, DC) (1891-1899)', 'value': 'Boundary Field', 'importance': 617}, {'label': 'American League Park I (Washington, DC) (1901-1903)', 'value': 'American League Park I', 'importance': 207}, {'label': 'American League Park II (Washington, DC) (1904-1910)', 'value': 'American League Park II', 'importance': 537}, {'label': 'Griffith Stadium (Washington, DC) (1911-1961)', 'value': 'Griffith Stadium', 'importance': 3945}, {'label': 'Robert F. Kennedy Stadium -- D.C. Stadium (Washington, DC) (1962-2007)', 'value': 'Robert F. Kennedy Stadium', 'importance': 1047}, {'label': 'Nationals Park (Washington, DC) (2008-2016)', 'value': 'Nationals Park', 'importance': 727}, {'label': 'Troy Ball Club Grounds (Watervliet, NY) (1882-1882)', 'value': 'Troy Ball Club Grounds', 'importance': 38}, {'label': 'Waverly Fairgrounds (Waverly, NJ) (1873-1873)', 'value': 'Waverly Fairgrounds', 'importance': 7}, {'label': 'Monitor Grounds (Weehawken, NJ) (1887-1887)', 'value': 'Monitor Grounds', 'importance': 1}, {'label': 'Island Grounds (Wheeling, WV) (1890-1890)', 'value': 'Island Grounds', 'importance': 1}, {'label': 'Union Street Park (Wilmington, DE) (1884-1884)', 'value': 'Union Street Park', 'importance': 7}, {'label': 'West New York Field Club Grounds (West New York, NJ) (1898-1899)', 'value': 'West New York Field Club Grounds', 'importance': 7}, {'label': 'Agricultural County Fair Grounds I (Worcester, MA) (1880-1882)', 'value': 'Agricultural County Fair Grounds I', 'importance': 126}, {'label': 'Agricultural County Fair Grounds II (Worcester, MA) (1887-1887)', 'value': 'Agricultural County Fair Grounds II', 'importance': 1}, {'label': 'Worcester Driving Park Grounds (Worcester, MA) (1874-1874)', 'value': 'Worcester Driving Park Grounds', 'importance': 1}];
		}
		else {
			this._stadiums = []
		}
		
		if (document.activeElement === this.input) {
			this.evaluate();
		}
	},

	get selected() {
		return this.index > -1;
	},

	get opened() {
		return this.isOpened;
	},

	close: function (o) {
		if (!this.opened) {
			return;
		}

		this.input.setAttribute("aria-expanded", "false");
		this.ul.setAttribute("hidden", "");
		this.isOpened = false;
		this.index = -1;

		this.status.setAttribute("hidden", "");

		$.fire(this.input, "awesomplete-close", o || {});
	},

	open: function () {
		this.input.setAttribute("aria-expanded", "true");
		this.ul.removeAttribute("hidden");
		this.isOpened = true;

		this.status.removeAttribute("hidden");

		if (this.autoFirst && this.index === -1) {
			this.goto(0);
		}

		$.fire(this.input, "awesomplete-open");
	},

	destroy: function() {
		//remove events from the input and its form
		$.unbind(this.input, this._events.input);
		$.unbind(this.input.form, this._events.form);

		// cleanup container if it was created by Awesomplete but leave it alone otherwise
		if (!this.options.container) {
			//move the input out of the awesomplete container and remove the container and its children
			var parentNode = this.container.parentNode;

			parentNode.insertBefore(this.input, this.container);
			parentNode.removeChild(this.container);
		}

		//remove autocomplete and aria-autocomplete attributes
		this.input.removeAttribute("autocomplete");
		this.input.removeAttribute("aria-autocomplete");

		//remove this awesomeplete instance from the global array of instances
		var indexOfAwesomplete = _.all.indexOf(this);

		if (indexOfAwesomplete !== -1) {
			_.all.splice(indexOfAwesomplete, 1);
		}
	},

	next: function () {
		var count = this.ul.children.length;
		this.goto(this.index < count - 1 ? this.index + 1 : (count ? 0 : -1) );
	},

	previous: function () {
		var count = this.ul.children.length;
		var pos = this.index - 1;

		this.goto(this.selected && pos !== -1 ? pos : count - 1);
	},

	// Should not be used, highlights specific item without any checks!
	goto: function (i) {
		var lis = this.ul.children;

		if (this.selected) {
			lis[this.index].setAttribute("aria-selected", "false");
		}

		this.index = i;

		if (i > -1 && lis.length > 0) {
			lis[i].setAttribute("aria-selected", "true");

			this.status.textContent = lis[i].textContent + ", list item " + (i + 1) + " of " + lis.length;

            this.input.setAttribute("aria-activedescendant", this.ul.id + "_item_" + this.index);

			// scroll to highlighted element in case parent's height is fixed
			this.ul.scrollTop = lis[i].offsetTop - this.ul.clientHeight + lis[i].clientHeight;

			
		}
	},

	select: function (selected, origin, originalEvent) {
		if (selected) {
			this.index = $.siblingIndex(selected);
		} else {
			selected = this.ul.children[this.index];
		}
		
		if (selected && this.index > -1) {
			var suggestion = this.suggestions[this.index];

			var allowed = $.fire(this.input, "awesomplete-select", {
				text: suggestion,
				origin: origin || selected,
				originalEvent: originalEvent
			});

			if (allowed) {
				this.replace(suggestion);
				this.close({ reason: "select" });
				$.fire(this.input, "awesomplete-selectcomplete", {
					text: suggestion,
					originalEvent: originalEvent,
				});
				window.location = this.options.urlbase+suggestion.id;
				
			}
		}
	},
	
	makelist: function(fulllist,value1,value3) {
		var me = this;
		var suggestions1 = [];
		var suggestions2 = [];
		var suggestions3 = [];
		var suggestions1s = [];
		var suggestions2s = [];
		var suggestions3s = [];
		var mItems = this.maxItems;
		
		
		if (value3.length > 2){
			var vl1t = value1.trim().toLowerCase();
			var vl2t = value3[1].trim().toLowerCase();
			var vl3t = value3[0].trim().toLowerCase();
			suggestions1 = fulllist
				.filter(function(item) {
					return item.value.indexOf(vl1t) > -1;
				});
			
			suggestions1s = suggestions1
				.filter(function(item) {
					return item.value.indexOf(vl1t) == 0 || item.value.indexOf(" "+vl1t) > -1;
				});
				
			suggestions2 = suggestions1
				.filter(function(item) {
					return item.value.indexOf(vl2t) > -1;
				});
			
			suggestions2s = suggestions1s
				.filter(function(item) {
					return item.value.indexOf(vl2t) == 0 || item.value.indexOf(" "+vl2t) > -1;
				});
			
			suggestions3 = suggestions2
				.filter(function(item) {
					return item.value.indexOf(vl3t) > -1;
				});
			
			suggestions3s = suggestions2s
				.filter(function(item) {
					return item.value.indexOf(vl3t) == 0 || item.value.indexOf(" "+vl3t) > -1;
				});
			

			suggestions3 = suggestions3.slice(0, mItems);
			suggestions2 = suggestions2.slice(0, mItems);
			suggestions1 = suggestions1.slice(0, mItems);
			suggestions1s = suggestions1s.slice(0, mItems);
			suggestions2s = suggestions2s.slice(0, mItems);
			suggestions3s = suggestions3s.slice(0, mItems);
		}
		else if (value3.length > 1) {
			var vl1t = value1.trim().toLowerCase();
			var vl2t = value3[0].trim().toLowerCase();
			suggestions1 = fulllist
				.filter(function(item) {
					return item.value.indexOf(vl1t) > -1;
				});
			suggestions1s = suggestions1
				.filter(function(item) {
					return item.value.indexOf(vl1t) == 0 || item.value.indexOf(" "+vl1t) > -1;
				});
			suggestions2 = suggestions1
				.filter(function(item) {
					return item.value.indexOf(vl2t) > -1;
				});
			suggestions2s = suggestions1s
				.filter(function(item) {
					return item.value.indexOf(vl2t) == 0 || item.value.indexOf(" "+vl2t) > -1;
				});
			

			suggestions2 = suggestions2.slice(0, mItems);
			suggestions1 = suggestions1.slice(0, mItems);
			suggestions1s = suggestions1s.slice(0, mItems);
			suggestions2s = suggestions2s.slice(0, mItems);
		}
		else {
			var vl1t = value1.trim().toLowerCase();
			console.log(vl1t);
			suggestions1 = fulllist
				.filter(function(item) {
					return item.value.indexOf(vl1t) > -1;
				})
			
			suggestions1s = suggestions1
				.filter(function(item) {
					return item.value.indexOf(vl1t) == 0 || item.value.indexOf(" "+vl1t) > -1;
				});
			
			suggestions1 = suggestions1.slice(0, mItems);
			suggestions1s = suggestions1s.slice(0, mItems);
			
		}
		
		var player_suggestions = suggestions3s.concat(suggestions3).concat(suggestions2s).concat(suggestions2).concat(suggestions1s).concat(suggestions1);

		if (suggestions1.length > 0) {
			player_suggestions = this.remove_dups(player_suggestions);
		}

		player_suggestions = player_suggestions.slice(0, mItems);

		
		player_suggestions.forEach(function(text, index) {
			me.ul.appendChild(me.item(text.label, "", index));
		});

		this.suggestions = player_suggestions;
	},
	
	evaluate: function() {
		var me = this;
		var inputArray = this.input.value.split(" ");
		var value1 = inputArray.slice(inputArray.length-1,inputArray.length)[0];
		var value3;
		if (inputArray.length > 2) {
			value3 = inputArray.slice(inputArray.length-3,inputArray.length);
		}
		else if (inputArray.length > 1) {
			value3 = inputArray.slice(inputArray.length-2,inputArray.length);
		}
		else {
			value3 = [];
		}

		if ((value1.length >= this.minChars || value3.length > 1) && this._list && this._list.length > 0) {
			this.index = -1;
			// Populate list with options that match
			this.ul.innerHTML = "";
			
			this.makelist(this._list,value1,value3);

			

			if (this.ul.children.length === 0) {

                this.status.textContent = "No results found";

				this.close({ reason: "nomatches" });

			} else {
				this.open();

                this.status.textContent = this.ul.children.length + " results found";
			}
			
		}
		else {
			this.close({ reason: "nomatches" });

                this.status.textContent = "No results found";
		}
	}
};

// Static methods/properties

_.all = [];

_.FILTER_CONTAINS = function (text, input) {
	return RegExp($.regExpEscape(input.trim()), "i").test(text);
};

_.FILTER_STARTSWITH = function (text, input) {
	return RegExp("^" + $.regExpEscape(input.trim()), "i").test(text);
};

_.SORT_BYLENGTH = function (a, b) {
	if (a.length !== b.length) {
		return a.length - b.length;
	}

	return a < b? -1 : 1;
};

_.PLAYER_SORT = function (a, b) {
	if (a.nwords !== b.nwords) {
		return b.nwords - a.nwords;
	}
	

	return b.importance - a.importance;
};

_.TEAM_SORT = function (a, b) {
	if (a.nwords !== b.nwords) {
		return b.nwords - a.nwords;
	}
	

	return b.importance - a.importance;
};

_.REMOVE_DUPS = function (list) {
	var unique_list = [];
	var listlen = list.length;
	for (var i=0;i<listlen;i++) {
		unique_list.push(list[i].value);
	}

	var jobsUnique = list.filter(function(item, index){
		return unique_list.indexOf(item.value) >= index;
	});	

	return jobsUnique;
};

_.CONTAINER = function (input) {
	return $.create("div", {
		className: "awesomplete",
		around: input
	});
}

_.ITEM = function (text, input, item_id) {
	var html = input.trim() === "" ? text : text.replace(RegExp($.regExpEscape(input.trim()), "gi"), "<mark>$&</mark>");
	return $.create("li", {
		innerHTML: html,
		"role": "option",
		"aria-selected": "false",
		"id": "awesomplete_list_" + this.count + "_item_" + item_id
	});
};

_.HEADER = function (text) {

	return $.create("li", {
		innerHTML: text,
		"role": "option",
		"aria-selected": "false",
		"id": "header"
	});
};

_.REPLACE = function (text) {
	var oldText = this.input.value.split(" ");
	var nwords = text.nwords;
	if (oldText.length > nwords) {
		oldText = oldText.slice(0,oldText.length-nwords).join(" ");
		this.input.value = oldText + " " + text.value;
	}
	else {
		this.input.value = text.value;
	}
	
};

_.DATA = function (item/*, input*/) { return item; };

// Private functions

function Suggestion(data,nwords) {
	var o = Array.isArray(data)
	  ? { label: data[0], value: data[1] }
	  : typeof data === "object" && "label" in data && "value" in data && "importance" in data ? data : { label: data, value: data };

	this.label = o.label || o.value;
	this.value = o.value;
	this.id = o.id || o.value;
	this.nwords = nwords;
	this.importance = o.importance;

}
Object.defineProperty(Suggestion.prototype = Object.create(String.prototype), "length", {
	get: function() { return this.label.length; }
});
Suggestion.prototype.toString = Suggestion.prototype.valueOf = function () {
	return "" + this.value;
};

function configure(instance, properties, o) {
	for (var i in properties) {
		var initial = properties[i],
		    attrValue = instance.input.getAttribute("data-" + i.toLowerCase());

		if (typeof initial === "number") {
			instance[i] = parseInt(attrValue);
		}
		else if (initial === false) { // Boolean options must be false by default anyway
			instance[i] = attrValue !== null;
		}
		else if (initial instanceof Function) {
			instance[i] = null;
		}
		else {
			instance[i] = attrValue;
		}

		if (!instance[i] && instance[i] !== 0) {
			instance[i] = (i in o)? o[i] : initial;
		}
	}
}

// Helpers

var slice = Array.prototype.slice;

function $(expr, con) {
	return typeof expr === "string"? (con || document).querySelector(expr) : expr || null;
}

function $$(expr, con) {
	return slice.call((con || document).querySelectorAll(expr));
}

$.create = function(tag, o) {
	var element = document.createElement(tag);

	for (var i in o) {
		var val = o[i];

		if (i === "inside") {
			$(val).appendChild(element);
		}
		else if (i === "around") {
			var ref = $(val);
			ref.parentNode.insertBefore(element, ref);
			element.appendChild(ref);

			if (ref.getAttribute("autofocus") != null) {
				ref.focus();
			}
		}
		else if (i in element) {
			element[i] = val;
		}
		else {
			element.setAttribute(i, val);
		}
	}

	return element;
};

$.bind = function(element, o) {
	if (element) {
		for (var event in o) {
			var callback = o[event];

			event.split(/\s+/).forEach(function (event) {
				element.addEventListener(event, callback);
			});
		}
	}
};

$.unbind = function(element, o) {
	if (element) {
		for (var event in o) {
			var callback = o[event];

			event.split(/\s+/).forEach(function(event) {
				element.removeEventListener(event, callback);
			});
		}
	}
};

$.fire = function(target, type, properties) {
	var evt = document.createEvent("HTMLEvents");

	evt.initEvent(type, true, true );

	for (var j in properties) {
		evt[j] = properties[j];
	}

	return target.dispatchEvent(evt);
};

$.regExpEscape = function (s) {
	return s.replace(/[-\\^$*+?.()|[\]{}]/g, "\\$&");
};

$.siblingIndex = function (el) {
	/* eslint-disable no-cond-assign */
	for (var i = 0; el = el.previousElementSibling; i++);
	return i;
};

// Initialization

function init() {
	var d = new Date();
	var n = d.getTime();
	console.log('first',n);
	Promise.all([d3.json("data/personJSON.json"),d3.json("data/boxesJSON.json")]).then(function(data) {
		retroids = Object.keys(data[0]);
		var nplayers = retroids.length;
		console.log(retroids);
		players = [];
		d = new Date();
  		n = d.getTime();
		console.log('loaded',n);
		for (var i=0;i<nplayers;i++) {
			var yearrange1 = data[0][retroids[i]][1].substring(0,3);
			var yearrange2 = data[0][retroids[i]][1].substring(3,6);
			if (parseInt(yearrange1) > 500) {
				yearrange1 = "1"+yearrange1;
			}
			else {
				yearrange1 = "2"+yearrange1;
			}
			if (parseInt(yearrange2) > 500) {
				yearrange2 = "1"+yearrange2;
			}
			else {
				yearrange2 = "2"+yearrange2;
			}
			players.push({label:data[0][retroids[i]][0]+" ("+yearrange1+"-"+yearrange2+")",value:data[0][retroids[i]][0].toLowerCase(),id:retroids[i],importance:data[0][retroids[i]][2]});
			
		}
		
		teamids = Object.keys(data[1]);
		var nteams = teamids.length;
		boxes = [];
		d = new Date();
  		n = d.getTime();
		console.log(n);
		for (var i=0;i<nteams;i++) {
			var years = Object.keys(data[1][teamids[i]]);
			for (var ii=0;ii<years.length;ii++) {
				var opps = Object.keys(data[1][teamids[i]][years[ii]]);
				for (var iii=0;iii<opps.length;iii++) {
					var games = data[1][teamids[i]][years[ii]][opps[iii]];
					for (var iiii=0;iiii<games.length;iiii++){
						
						if (games[iiii].length > 4) {
							boxes.push({label:shiohteams[opps[iii]][years[ii]][2]+' @ '+shiohteams[teamids[i]][years[ii]][2]+' '+games[iiii].substring(0,2)+'/'+games[iiii].substring(2,4)+'/'+years[ii],value:shiohteams[opps[iii]][years[ii]][0].toLowerCase()+' @ '+shiohteams[teamids[i]][years[ii]][0].toLowerCase()+' '+games[iiii].substring(0,2)+'/'+games[iiii].substring(2,4)+'/'+years[ii],id:teamids[i]+years[ii]+games[iiii],importance:parseInt(years[ii])*10000+parseInt(games[iiii])/10});
						}
						else {
							boxes.push({label:shiohteams[opps[iii]][years[ii]][2]+' @ '+shiohteams[teamids[i]][years[ii]][2]+' '+games[iiii].substring(0,2)+'/'+games[iiii].substring(2,4)+'/'+years[ii],value:shiohteams[opps[iii]][years[ii]][0].toLowerCase()+' @ '+shiohteams[teamids[i]][years[ii]][0].toLowerCase()+' '+games[iiii].substring(0,2)+'/'+games[iiii].substring(2,4)+'/'+years[ii],id:teamids[i]+years[ii]+games[iiii]+'0',importance:parseInt(years[ii])*10000+parseInt(games[iiii])});
						}
					}
				}
			}
			
		}
		d = new Date();
  		n = d.getTime();
		console.log('presort',n);
		boxes.sort(function (a,b) { return b.importance - a.importance;});
		d = new Date();
  		n = d.getTime();
		console.log('postsort',n);
		$$("input.awesompletePlayer").forEach(function (input) {
			new _(input, {urlbase:'player.html?id='}, players);
		});
		teams = [{"label": "Boston Braves (1876-1952)", "value": "Boston Braves", "importance": 1952}, {"label": "Chicago Cubs (1876-2016)", "value": "Chicago Cubs", "importance": 2016}, {"label": "Cincinnati Reds (1876-1880)", "value": "Cincinnati Reds", "importance": 1880}, {"label": "Hartford Dark Blues (1876-1877)", "value": "Hartford Dark Blues", "importance": 1877}, {"label": "Louisville Grays (1876-1877)", "value": "Louisville Grays", "importance": 1877}, {"label": "New York Mutuals (1876-1876)", "value": "New York Mutuals", "importance": 1876}, {"label": "Philadelphia Athletics (1876-1876)", "value": "Philadelphia Athletics", "importance": 1876}, {"label": "St. Louis Brown Stockings (1876-1877)", "value": "St. Louis Brown Stockings", "importance": 1877}, {"label": "Indianapolis Blues (1878-1878)", "value": "Indianapolis Blues", "importance": 1878}, {"label": "Milwaukee Grays (1878-1878)", "value": "Milwaukee Grays", "importance": 1878}, {"label": "Providence Grays (1878-1885)", "value": "Providence Grays", "importance": 1885}, {"label": "Buffalo Bisons (1879-1885)", "value": "Buffalo Bisons", "importance": 1885}, {"label": "Cleveland Blues (1879-1884)", "value": "Cleveland Blues", "importance": 1884}, {"label": "Syracuse Stars (1879-1879)", "value": "Syracuse Stars", "importance": 1879}, {"label": "Troy Trojans (1879-1882)", "value": "Troy Trojans", "importance": 1882}, {"label": "Worcester Ruby Legs (1880-1882)", "value": "Worcester Ruby Legs", "importance": 1882}, {"label": "Detroit Wolverines (1881-1888)", "value": "Detroit Wolverines", "importance": 1888}, {"label": "New York Giants (1883-1957)", "value": "New York Giants", "importance": 1957}, {"label": "Philadelphia Phillies (1883-2016)", "value": "Philadelphia Phillies", "importance": 2016}, {"label": "St. Louis Maroons (1885-1886)", "value": "St. Louis Maroons", "importance": 1886}, {"label": "Kansas City Cowboys (1886-1886)", "value": "Kansas City Cowboys", "importance": 1886}, {"label": "Washington Nationals (1886-1889)", "value": "Washington Nationals", "importance": 1889}, {"label": "Indianapolis Hoosiers (1887-1889)", "value": "Indianapolis Hoosiers", "importance": 1889}, {"label": "Pittsburgh Pirates (1887-2016)", "value": "Pittsburgh Pirates", "importance": 2016}, {"label": "Cleveland Spiders (1889-1899)", "value": "Cleveland Spiders", "importance": 1899}, {"label": "Brooklyn Dodgers (1890-1957)", "value": "Brooklyn Dodgers", "importance": 1957}, {"label": "Cincinnati Reds (1890-2016)", "value": "Cincinnati Reds", "importance": 2016}, {"label": "Baltimore Orioles (1892-1899)", "value": "Baltimore Orioles", "importance": 1899}, {"label": "Louisville Colonels (1892-1899)", "value": "Louisville Colonels", "importance": 1899}, {"label": "St. Louis Cardinals (1892-2016)", "value": "St. Louis Cardinals", "importance": 2016}, {"label": "Washington Nationals (1892-2016)", "value": "Washington Nationals", "importance": 2016}, {"label": "Baltimore Orioles (1901-1902)", "value": "Baltimore Orioles", "importance": 1902}, {"label": "Boston Red Sox (1901-2016)", "value": "Boston Red Sox", "importance": 2016}, {"label": "Chicago White Sox (1901-2016)", "value": "Chicago White Sox", "importance": 2016}, {"label": "Cleveland Indians (1901-2016)", "value": "Cleveland Indians", "importance": 2016}, {"label": "Detroit Tigers (1901-2016)", "value": "Detroit Tigers", "importance": 2016}, {"label": "Milwaukee Brewers (1901-1901)", "value": "Milwaukee Brewers", "importance": 1901}, {"label": "Philadelphia Athletics (1901-1954)", "value": "Philadelphia Athletics", "importance": 1954}, {"label": "Washington Senators (1901-1960)", "value": "Washington Senators", "importance": 1960}, {"label": "St. Louis Browns (1902-1953)", "value": "St. Louis Browns", "importance": 1953}, {"label": "New York Yankees (1903-2016)", "value": "New York Yankees", "importance": 2016}, {"label": "Milwaukee Braves (1953-1965)", "value": "Milwaukee Braves", "importance": 1965}, {"label": "Baltimore Orioles (1954-2016)", "value": "Baltimore Orioles", "importance": 2016}, {"label": "Kansas City Athletics (1955-1967)", "value": "Kansas City Athletics", "importance": 1967}, {"label": "Los Angeles Dodgers (1958-2016)", "value": "Los Angeles Dodgers", "importance": 2016}, {"label": "San Francisco Giants (1958-2016)", "value": "San Francisco Giants", "importance": 2016}, {"label": "Los Angeles Angels of Anaheim (1961-2016)", "value": "Los Angeles Angels of Anaheim", "importance": 2016}, {"label": "Minnesota Twins (1961-2016)", "value": "Minnesota Twins", "importance": 2016}, {"label": "Washington Senators (1961-1971)", "value": "Washington Senators", "importance": 1971}, {"label": "Houston Astros (1962-2016)", "value": "Houston Astros", "importance": 2016}, {"label": "New York Mets (1962-2016)", "value": "New York Mets", "importance": 2016}, {"label": "California Angels (1965-1996)", "value": "California Angels", "importance": 1996}, {"label": "Atlanta Braves (1966-2016)", "value": "Atlanta Braves", "importance": 2016}, {"label": "Oakland Athletics (1968-2016)", "value": "Oakland Athletics", "importance": 2016}, {"label": "Kansas City Royals (1969-2016)", "value": "Kansas City Royals", "importance": 2016}, {"label": "Montreal Expos (1969-2004)", "value": "Montreal Expos", "importance": 2004}, {"label": "San Diego Padres (1969-2016)", "value": "San Diego Padres", "importance": 2016}, {"label": "Seattle Pilots (1969-1969)", "value": "Seattle Pilots", "importance": 1969}, {"label": "Milwaukee Brewers (1970-1997)", "value": "Milwaukee Brewers", "importance": 1997}, {"label": "Texas Rangers (1972-2016)", "value": "Texas Rangers", "importance": 2016}, {"label": "Seattle Mariners (1977-2016)", "value": "Seattle Mariners", "importance": 2016}, {"label": "Toronto Blue Jays (1977-2016)", "value": "Toronto Blue Jays", "importance": 2016}, {"label": "Colorado Rockies (1993-2016)", "value": "Colorado Rockies", "importance": 2016}, {"label": "Florida Marlins (1993-2011)", "value": "Florida Marlins", "importance": 2011}, {"label": "Anaheim Angels (1997-2004)", "value": "Anaheim Angels", "importance": 2004}, {"label": "Arizona Diamondbacks (1998-2016)", "value": "Arizona Diamondbacks", "importance": 2016}, {"label": "Milwaukee Brewers (1998-2016)", "value": "Milwaukee Brewers", "importance": 2016}, {"label": "Tampa Bay Rays (1998-2016)", "value": "Tampa Bay Rays", "importance": 2016}, {"label": "Miami Marlins (2012-2016)", "value": "Miami Marlins", "importance": 2016}, {"label": "Atlanta Braves Franchise (1876-2016)", "value": "Atlanta Braves", "importance": 2016}, {"label": "Chicago Cubs Franchise (1876-2016)", "value": "Chicago Cubs", "importance": 2016}, {"label": "Cincinnati Reds Franchise (1876-1880)", "value": "Cincinnati Reds", "importance": 1880}, {"label": "Hartford Dark Blues Franchise (1876-1877)", "value": "Hartford Dark Blues", "importance": 1877}, {"label": "Louisville Grays Franchise (1876-1877)", "value": "Louisville Grays", "importance": 1877}, {"label": "New York Mutuals Franchise (1876-1876)", "value": "New York Mutuals", "importance": 1876}, {"label": "Philadelphia Athletics Franchise (1876-1876)", "value": "Philadelphia Athletics", "importance": 1876}, {"label": "St. Louis Brown Stockings Franchise (1876-1877)", "value": "St. Louis Brown Stockings", "importance": 1877}, {"label": "Indianapolis Blues Franchise (1878-1878)", "value": "Indianapolis Blues", "importance": 1878}, {"label": "Milwaukee Grays Franchise (1878-1878)", "value": "Milwaukee Grays", "importance": 1878}, {"label": "Providence Grays Franchise (1878-1885)", "value": "Providence Grays", "importance": 1885}, {"label": "Buffalo Bisons Franchise (1879-1885)", "value": "Buffalo Bisons", "importance": 1885}, {"label": "Cleveland Blues Franchise (1879-1884)", "value": "Cleveland Blues", "importance": 1884}, {"label": "Syracuse Stars Franchise (1879-1879)", "value": "Syracuse Stars", "importance": 1879}, {"label": "Troy Trojans Franchise (1879-1882)", "value": "Troy Trojans", "importance": 1882}, {"label": "Worcester Ruby Legs Franchise (1880-1882)", "value": "Worcester Ruby Legs", "importance": 1882}, {"label": "Detroit Wolverines Franchise (1881-1888)", "value": "Detroit Wolverines", "importance": 1888}, {"label": "San Francisco Giants Franchise (1883-2016)", "value": "San Francisco Giants", "importance": 2016}, {"label": "Philadelphia Phillies Franchise (1883-2016)", "value": "Philadelphia Phillies", "importance": 2016}, {"label": "St. Louis Maroons Franchise (1885-1886)", "value": "St. Louis Maroons", "importance": 1886}, {"label": "Kansas City Cowboys Franchise (1886-1886)", "value": "Kansas City Cowboys", "importance": 1886}, {"label": "Washington Nationals Franchise (1886-1889)", "value": "Washington Nationals", "importance": 1889}, {"label": "Indianapolis Hoosiers Franchise (1887-1889)", "value": "Indianapolis Hoosiers", "importance": 1889}, {"label": "Pittsburgh Pirates Franchise (1887-2016)", "value": "Pittsburgh Pirates", "importance": 2016}, {"label": "Cleveland Spiders Franchise (1889-1899)", "value": "Cleveland Spiders", "importance": 1899}, {"label": "Los Angeles Dodgers Franchise (1890-2016)", "value": "Los Angeles Dodgers", "importance": 2016}, {"label": "Cincinnati Reds Franchise (1890-2016)", "value": "Cincinnati Reds", "importance": 2016}, {"label": "Baltimore Orioles Franchise (1892-1899)", "value": "Baltimore Orioles", "importance": 1899}, {"label": "Louisville Colonels Franchise (1892-1899)", "value": "Louisville Colonels", "importance": 1899}, {"label": "St. Louis Cardinals Franchise (1892-2016)", "value": "St. Louis Cardinals", "importance": 2016}, {"label": "Washington Senators Franchise (1892-1899)", "value": "Washington Senators", "importance": 1899}, {"label": "New York Yankees Franchise (1901-2016)", "value": "New York Yankees", "importance": 2016}, {"label": "Boston Red Sox Franchise (1901-2016)", "value": "Boston Red Sox", "importance": 2016}, {"label": "Chicago White Sox Franchise (1901-2016)", "value": "Chicago White Sox", "importance": 2016}, {"label": "Cleveland Indians Franchise (1901-2016)", "value": "Cleveland Indians", "importance": 2016}, {"label": "Detroit Tigers Franchise (1901-2016)", "value": "Detroit Tigers", "importance": 2016}, {"label": "Baltimore Orioles Franchise (1901-2016)", "value": "Baltimore Orioles", "importance": 2016}, {"label": "Oakland Athletics Franchise (1901-2016)", "value": "Oakland Athletics", "importance": 2016}, {"label": "Minnesota Twins Franchise (1901-2016)", "value": "Minnesota Twins", "importance": 2016}, {"label": "Los Angeles Angels of Anaheim Franchise (1961-2016)", "value": "Los Angeles Angels of Anaheim", "importance": 2016}, {"label": "Texas Rangers Franchise (1961-2016)", "value": "Texas Rangers", "importance": 2016}, {"label": "Houston Astros Franchise (1962-2016)", "value": "Houston Astros", "importance": 2016}, {"label": "New York Mets Franchise (1962-2016)", "value": "New York Mets", "importance": 2016}, {"label": "Kansas City Royals Franchise (1969-2016)", "value": "Kansas City Royals", "importance": 2016}, {"label": "Washington Nationals Franchise (1969-2016)", "value": "Washington Nationals", "importance": 2016}, {"label": "San Diego Padres Franchise (1969-2016)", "value": "San Diego Padres", "importance": 2016}, {"label": "Milwaukee Brewers Franchise (1969-2016)", "value": "Milwaukee Brewers", "importance": 2016}, {"label": "Seattle Mariners Franchise (1977-2016)", "value": "Seattle Mariners", "importance": 2016}, {"label": "Toronto Blue Jays Franchise (1977-2016)", "value": "Toronto Blue Jays", "importance": 2016}, {"label": "Colorado Rockies Franchise (1993-2016)", "value": "Colorado Rockies", "importance": 2016}, {"label": "Florida Marlins Franchise (1993-2016)", "value": "Florida Marlins", "importance": 2016}, {"label": "Arizona Diamondbacks Franchise (1998-2016)", "value": "Arizona Diamondbacks", "importance": 2016}, {"label": "Tampa Bay Rays Franchise (1998-2016)", "value": "Tampa Bay Rays", "importance": 2016}];
		$$("input.awesompleteTeam").forEach(function (input) {
			new _(input, {urlbase:'team.html?id='}, teams);
		});
		
		$$("input.awesompleteBox").forEach(function (input) {
			new _(input, {urlbase:'boxscore.html?id='}, boxes);
		});
		
		d = new Date();
  		n = d.getTime();
		console.log('created',n);
	})
	
}

// Make sure to export Awesomplete on self when in a browser
if (typeof self !== "undefined") {
	self.Awesomplete = _;
}

// Are we in a browser? Check for Document constructor
if (typeof Document !== "undefined") {
	// DOM already loaded?
	if (document.readyState !== "loading") {
		init();
	}
	else {
		// Wait for it
		document.addEventListener("DOMContentLoaded", init);
	}
}

_.$ = $;
_.$$ = $$;

// Expose Awesomplete as a CJS module
if (typeof module === "object" && module.exports) {
	module.exports = _;
}

return _;

}());
