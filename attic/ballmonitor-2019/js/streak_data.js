
    	


var playerData = [];
var careerData;
var bestGames = [];
var data;
var statsVisible = {0:'number',1:false};
var streakid;
var myData = [];



function decodeLeader(rawstr) {
	str = decodeURIComponent(rawstr).replace(/\s/g, "").toLowerCase();
	return str;
}

function getAllUrlParams(url) {

  // get query string from url (optional) or window
  var queryString = url ? url.split('?')[1] : window.location.search.slice(1);

  // we'll store the parameters here
  var obj = {};

  // if query string exists
  if (queryString) {

    // stuff after # is not part of query string, so get rid of it
    queryString = queryString.split('#')[0];

    // split our query string into its component parts
    var arr = queryString.split('&');

    for (var i = 0; i < arr.length; i++) {
      // separate the keys and the values
      var a = arr[i].split('=');

      // set parameter name and value (use 'true' if empty)
      var paramName = a[0];
      var paramValue = typeof (a[1]) === 'undefined' ? true : a[1];

      // (optional) keep case consistent
      paramName = paramName.toLowerCase();
      if (typeof paramValue === 'string') paramValue = paramValue.toLowerCase();

      // if the paramName ends with square brackets, e.g. colors[] or colors[2]
      if (paramName.match(/\[(\d+)?\]$/)) {

        // create key if it doesn't exist
        var key = paramName.replace(/\[(\d+)?\]/, '');
        if (!obj[key]) obj[key] = [];

        // if it's an indexed array e.g. colors[2]
        if (paramName.match(/\[\d+\]$/)) {
          // get the index value and add the entry at the appropriate position
          var index = /\[(\d+)\]/.exec(paramName)[1];
          obj[key][index] = paramValue;
        } else {
          // otherwise add the value to the end of the array
          obj[key].push(paramValue);
        }
      } else {
        // we're dealing with a string
        if (!obj[paramName]) {
          // if it doesn't exist, create property
          obj[paramName] = paramValue;
        } else if (obj[paramName] && typeof obj[paramName] === 'string'){
          // if property does exist and it's a string, convert it to an array
          obj[paramName] = [obj[paramName]];
          obj[paramName].push(paramValue);
        } else {
          // otherwise add the property
          obj[paramName].push(paramValue);
        }
      }
    }
  }

  return obj;
}

function loadStreaks() {
	var request = new XMLHttpRequest();
	var getParams = getAllUrlParams();
	

	streakid = decodeLeader(getParams.formula.replace(/\+/g,' '));
	var borp = getParams.borps ? decodeLeader(getParams.borps) : 'b';
	var sorc = getParams.sorc ? decodeLeader(getParams.sorc) : '0';
	var splitcol = getParams.splitcol ? decodeLeader(getParams.splitcol) : '0';
	var minYear = getParams.minyear ? parseInt(decodeLeader(getParams.minyear)) - 1900 : 0;
	var maxYear = getParams.maxyear ? parseInt(decodeLeader(getParams.maxyear)) - 1900 : 200;
	var minAge = getParams.minage ? parseInt(decodeLeader(getParams.minage)) : 0;
	var maxAge = getParams.maxage ? parseInt(decodeLeader(getParams.maxage)) : 99;
	var month = getParams.month ? decodeLeader(getParams.month) : 'any';
	var date = getParams.date ? decodeLeader(getParams.date) : '99';
	var teamid = getParams.teamid ? decodeLeader(getParams.teamid) : '99';
	var oppid = getParams.oppid ? decodeLeader(getParams.oppid) : '99';

	

	minY = '0'+'0'+minYear;
	minY = minY.substring(minY.length-3,minY.length);
	if (maxYear > 120) {
		maxY = '200';
	}
	else {
		maxY = '0'+'0'+maxYear;
		maxY = maxY.substring(maxY.length-3,maxY.length);
	}
	if (minAge < 17) {
		minA = '00';
	}
	else {
		minA = '0'+minAge;
		minA = minA.substring(minA.length-2,minA.length);
	}
	if (maxAge > 49) {
		maxA = '99';
	}
	else {
		maxA = '0'+maxAge;
		maxA = maxA.substring(maxA.length-2,maxA.length);
	}
	if (month == 'any') {month = '99';}
	else if (month == 'march') {month = '03';}
	else if (month == 'april') {month = '04';}
	else if (month == 'may') {month = '05';}
	else if (month == 'june') {month = '06';}
	else if (month == 'july') {month = '07';}
	else if (month == 'august') {month = '08';}
	else if (month == 'september') {month = '09';}
	else if (month == 'october') {month = '10';}
	else if (month == 'november') {month = '11';}
	
	if (date == 'any') {
		date = '99';
	}
	else {
		date = '0'+date;
		date = date.substring(date.length-2,date.length);
	}
	
	if (teamid == 'any') {
		teamid = '99';
	}
	else {
		teamid = '0'+teamid;
		teamid = teamid.substring(teamid.length-2,teamid.length);
	}
	
	if (oppid == 'any') {
		oppid = '99';
	}
	else {
		oppid = '0'+oppid;
		oppid = oppid.substring(oppid.length-2,oppid.length);
	}
	

	//month = str('0'+str(month))[-2:] if month > -1 else '99'
	//day = str('0'+str(day))[-2:] if day > -1 else '99'
	//teamid = str('0'+str(teamid))[-2:] if teamid > -1 else '99'
	//oppid = str('0'+str(oppid))[-2:] if oppid > -1 else '99'
	
	//splitstr = sorc+spcol+minY+maxY+minA+maxA+month+day+teamid+oppid;
	splitstr = ''+sorc+''+splitcol+''+minY+''+maxY+''+minA+''+maxA+''+month+''+date+''+teamid+''+oppid;
	
	console.log(streakid, borp, splitstr);
	
	
	
	
	//statDisplay = [4,6,7,8,9,14];
	//stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
	if (borp == 'p'){
		request.open('GET', 'http://localhost:8000/streaksp?formula='+streakid, true);
	}
	else {
		request.open('GET', 'http://localhost:8000/streaks?formula='+splitstr+streakid, true);
	}
	request.onload = function() {
	  // Begin accessing JSON data here
	  data = JSON.parse(this.response);

	  if (request.status >= 200 && request.status < 400) {
	  	console.log(data['time']);
	  	console.log(data['streaks']);
		
		myData = [];
		if (data['streaks'][0][1].split.name != 'None') {
			for (var i=0;i<data['streaks'].length;i++){
				myData.push([data['streaks'][i][1].dates, data['streaks'][i][1].split.value,shiohplayers[data['streaks'][i][1].stats[0]][0],data['streaks'][i][0],data['streaks'][i][1].stats[4]]);
			}
	
			var columns = ['Dates',data['streaks'][0][1].split.name,'Name',streakid.toUpperCase(),'PA'];
			
		}
		else {
			for (var i=0;i<data['streaks'].length;i++){
				myData.push([data['streaks'][i][1].dates, shiohplayers[data['streaks'][i][1].stats[0]][0],data['streaks'][i][0],data['streaks'][i][1].stats[4]]);
			}
	
			var columns = ['Dates', 'Name',streakid.toUpperCase(),'PA'];

		}
		createPlayerStats(columns);
		//createPlayerStats(statDisplay);
	  } else {
		console.log('error')
	  }
	}

	request.send();
	
	//statDisplay = [4];
	//streakid = streakid.split('or').join('');
	//streakid = streakid.split('and').join('');
	//for (var i=0;i<stats.length-1;i++) {
	//	if (streakid.indexOf(stats[stats.length-1-i].toLowerCase()) > -1 ) {
	//		statDisplay.push(stats.length-1-i+4);
	//		streakid = streakid.split(stats[stats.length-1-i].toLowerCase()).join('');
	//	}
	//}
	//if (statDisplay.length < 6) {
	//	
	//} 
	//console.log(statDisplay);
}


function createPlayerStats(columns) {
	//stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
	//var columns = ['games','name','game1','game-1'];
    //for (var i=0;i<statDisplay.length;i++) {
    //	columns.push(stats[statDisplay[i]-4]);
    //}
	var table = d3.select('#streaks')
						.append('table')
						.attr('class','stats_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','streaksBody');
	

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(myData)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d) { return d; });
	  
	  

}

function chgStats(statid) {

	var thisStat = document.getElementById('stat'+statid);
	if (statsVisible[statid] == 'chart') {
		thisStat.classList.remove('btn-success');
		thisStat.classList.add('disabled');
		thisStat.classList.add('btn-secondary');
		statsVisible[statid]=false;
		removeCol(statid+6);
		
	}
	else if (statsVisible[statid] == 'number') {
		thisStat.classList.remove('btn-primary');
		thisStat.classList.add('btn-success');
		statsVisible[statid]='chart';
		makeChart(statid+6);
	}
	else {
		thisStat.classList.remove('btn-secondary');
		thisStat.classList.remove('disabled');
		thisStat.classList.add('btn-primary');
		statsVisible[statid]='number';
	}
	console.log(statid);
}

function makeChart(statcol) {
	var streaksBody = document.getElementById("streaksBody")
	for (var i=0;i<20;i++) {
		var sparkline1 = new Sparkbar(streaksBody.querySelectorAll('tr')[i].querySelectorAll('td')[statcol]);
		var statVals = [];
		var myData = data['streaks'][i][1];
		
		for (var ii=0;ii<myData.games.length;ii++) {
			statVals.push(myData.games[ii][statcol]);
		}
		sparkline1.draw(statVals);
    }
}




