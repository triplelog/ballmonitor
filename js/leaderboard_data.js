
    	

function updateSlider(value) {
	addGame(value);
}


var myData = [];
var baseColumns = [];
var displayColumns = [1,2,3,10];
var compColumns = [];
var statsVisible = [true,false];
var leaderid;
var splitcol = -1;
var borp;
var datatype = 'leaders';
  


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

function loadLeaders(newdata,reloadLeaders=false) {
	d = new Date();
  	n = d.getTime();
  	console.log('clicked',n);
	datatype = newdata;
	var request = new XMLHttpRequest();
	if (reloadLeaders) {
		leaderid = decodeLeader(document.getElementById('formula').value);
		borp =  document.querySelector('input[name="borp"]:checked').value;
		var sorc = document.querySelector('input[name="sorc"]:checked').value;
		var splitcol = document.querySelector('input[name="splitcol"]:checked').value;
		var minYear =  parseInt(decodeLeader(document.getElementById('minYear').value)) - 1900;
		var maxYear =  parseInt(decodeLeader(document.getElementById('maxYear').value)) - 1900;
		var minAge =  parseInt(decodeLeader(document.getElementById('minAge').value));
		var maxAge =  parseInt(decodeLeader(document.getElementById('maxAge').value));
		var month =  decodeLeader(document.getElementById('month').value);
		var date = decodeLeader(document.getElementById('date').value);
		var teamid = decodeLeader(document.getElementById('teamid').value);
		var oppid =  decodeLeader(document.getElementById('oppid').value);
		var maxgames =  decodeLeader(document.getElementById('maxgames').value);
		var regpost =  decodeLeader(document.getElementById('regpost').value);
		var revsort =  decodeLeader(document.getElementById('revsort').value);
		var countif =  decodeLeader(document.getElementById('countif').value);
		console.log(borp);
	}
	else {
		var getParams = getAllUrlParams();
		
		borp = getParams.borpl ? decodeLeader(getParams.borpl) : 'b';
		borp = getParams.borps ? decodeLeader(getParams.borpl) : borp;
		borp = getParams.borpg ? decodeLeader(getParams.borpl) : borp;
		borp = getParams.borpc ? decodeLeader(getParams.borpl) : borp;
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
		var maxgames = getParams.maxgames ? decodeLeader(getParams.maxgames) : '000';
		var regpost = getParams.regpost ? decodeLeader(getParams.regpost) : '0';
		var revsort = getParams.revsort ? decodeLeader(getParams.revsort) : '0';
		var countif = getParams.countif ? decodeLeader(getParams.countif) : '0';
		
		
		
		document.getElementById('month').value = month[0].toUpperCase() + month.substring(1);
		document.getElementById('date').value = parseInt(getParams.date) ? parseInt(getParams.date) : 'Any';
		document.getElementById('teamid').value = parseInt(getParams.teamid) ? parseInt(getParams.teamid) : 'Any';
		document.getElementById('oppid').value = parseInt(getParams.oppid) ? parseInt(getParams.oppid) : 'Any';
		document.getElementById('maxgames').value = parseInt(getParams.maxgames) ? parseInt(getParams.maxgames) : '0';
		
		
		
		var slider1 = document.getElementById('yearSlider');

		noUiSlider.create(slider1, {
			start: [Math.max(minYear + 1900,1900), Math.min(maxYear + 1900,2018)],
			step: 1,
			pips: {
				mode: 'values',
				values: [1900,1920,1940,1960,1980,2000,2018],
				density: 3
			},
			behaviour: 'drag',
			connect: true,
			range: {
				'min': 1900,
				'max': 2018
			}
		});
		document.getElementById('minYear').value = Math.max(minYear + 1900,1900);
		document.getElementById('maxYear').value = Math.min(maxYear + 1900,2018);

		slider1.noUiSlider.on('update', function (values) { 
			
			
			document.getElementById('minYear').value = parseInt(values[0]);
			document.getElementById('maxYear').value = parseInt(values[1]);
			pipvalues = [1900,2018];
			pvalues = [parseInt(values[0]),parseInt(values[1])];
			for (var i=0;i<2;i++) {
				if (Math.abs(pipvalues[i]-parseInt(values[0]))<20 || Math.abs(pipvalues[i]-parseInt(values[1]))<20 || Math.abs(pipvalues[i]-pvalues[pvalues.length-1])<20){
				
				}
				else {
					pvalues.push(pipvalues[i]);
				}
			}
			slider1.noUiSlider.pips({mode: 'values', values:pvalues, density: 3});
			
			var allMarkers = document.getElementById('yearSlider').querySelectorAll('.noUi-marker');
			for (var i=0;i<allMarkers.length;i++){
				if ( parseFloat(allMarkers[i].style.left) > -.01 + (parseFloat(values[0])-1900)*100/118 && parseFloat(allMarkers[i].style.left) < .01 + (parseFloat(values[1])-1900)*100/118) {
					allMarkers[i].style.background = 'red';
				}
				else {
					allMarkers[i].style.background = 'gray';
				}
			}
		});
		
		var slider2 = document.getElementById('ageSlider');

		noUiSlider.create(slider2, {
			start: [Math.max(minAge,16), Math.min(maxAge,50)],
			step: 1,
			pips: {
				mode: 'values',
				values: [16,20,25,30,35,40,45,50],
				density: 3
			},
			behaviour: 'drag',
			connect: true,
			range: {
				'min': 16,
				'max': 50
			}
		});	 
		
		document.getElementById('minAge').value = minAge;
		document.getElementById('maxAge').value = maxAge;
		slider2.noUiSlider.on('update', function (values) { 
			
			
			document.getElementById('minAge').value = parseInt(values[0]);
			document.getElementById('maxAge').value = parseInt(values[1]);
			pipvalues = [16,50];
			pvalues = [parseInt(values[0]),parseInt(values[1])];
			for (var i=0;i<2;i++) {
				if (Math.abs(pipvalues[i]-parseInt(values[0]))<5 || Math.abs(pipvalues[i]-parseInt(values[1]))<5 || Math.abs(pipvalues[i]-pvalues[pvalues.length-1])<5){
				
				}
				else {
					pvalues.push(pipvalues[i]);
				}
			}
			slider2.noUiSlider.pips({mode: 'values', values:pvalues, density: 3});
			
			var allMarkers = document.getElementById('ageSlider').querySelectorAll('.noUi-marker');
			for (var i=0;i<allMarkers.length;i++){
				if ( parseFloat(allMarkers[i].style.left) > -.01 + (parseFloat(values[0])-16)*100/34 && parseFloat(allMarkers[i].style.left) < .01 + (parseFloat(values[1])-16)*100/34) {
					allMarkers[i].style.background = 'red';
				}
				else {
					allMarkers[i].style.background = 'gray';
				}
			}
		});
		
		if (!getParams.formula) {
			return 0;
		}
		leaderid = decodeLeader(getParams.formula.replace(/\+/g,' '));
		document.getElementById('formula').value = leaderid;
	}
	

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
	
	if (isNaN(maxgames) || parseInt(maxgames) < 1 ) {
		maxgames = '000';
	}
	else if (parseInt(maxgames) >999 ) {
		maxgames = '999';
	}
	else {
		maxgames = '000'+maxgames;
		maxgames = maxgames.substring(maxgames.length-3,maxgames.length);
	}
	

	if (revsort =='0'){
		if (countif == '0') {sortcountif = '0';}
		else {sortcountif = '2';}
	}
	else {
		if (countif == '0') {sortcountif = '1';}
		else {sortcountif = '3';}
	}
	

	//month = str('0'+str(month))[-2:] if month > -1 else '99'
	//day = str('0'+str(day))[-2:] if day > -1 else '99'
	//teamid = str('0'+str(teamid))[-2:] if teamid > -1 else '99'
	//oppid = str('0'+str(oppid))[-2:] if oppid > -1 else '99'
	
	//splitstr = sorc+spcol+minY+maxY+minA+maxA+month+day+teamid+oppid;
	splitstr = ''+sorc+''+splitcol+''+minY+''+maxY+''+minA+''+maxA+''+month+''+date+''+teamid+''+oppid+''+maxgames+''+regpost+''+sortcountif;
	
	
	console.log(leaderid, borp, splitstr);
	
	if (borp == 'b' || borp == 'B'){
		request.open('GET', 'http://localhost:8000/'+datatype+'?formula='+splitstr+leaderid, true);
	}
	else {
		request.open('GET', 'http://localhost:8000/'+datatype+'p?formula='+splitstr+leaderid, true);
	}
	request.onload = function() {
	  // Begin accessing JSON data here
	  data = JSON.parse(this.response);

	  if (request.status >= 200 && request.status < 400) {
	  	d = new Date();
		n = d.getTime();
		console.log('all data:',n);
	  	console.log(data['time']);
	  	//console.log(data[datatype]);
		myData = [];
		statse = [4,23];
		//statse = [4,23];
		console.log(datatype);
		if (datatype == 'correls') {
			document.getElementById('correls').style.display = 'inline-block';
			createCorrels(data['correls']);
			return 0;
		}
		else if (datatype == 'bars') {
			document.getElementById('bars').style.display = 'inline-block';
			loadRace(data['bars']);
			return 0;
		}
		if (data[datatype][0][1].split.name != 'None') {
			if (data[datatype][0][1].year != '0') {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					dataRow = [data[datatype][i][1].year, data[datatype][i][1].split.value,playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = ['Year',data[datatype][0][1].split.name,'Name',leaderid.toUpperCase()];
			}
			else if (data[datatype][0][1].dates != '0') {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					
					dataRow = [data[datatype][i][1].dates, data[datatype][i][1].split.value,playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = ['Date',data[datatype][0][1].split.name,'Name',leaderid.toUpperCase()];
			}
			else {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					
					dataRow = [data[datatype][i][1].split.value,playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = [data[datatype][0][1].split.name,'Name',leaderid.toUpperCase()];
			}
		}
		else {
			if (data[datatype][0][1].year != '0') {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					
					dataRow = [data[datatype][i][1].year, playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = ['Year', 'Name',leaderid.toUpperCase()];
			}
			else if (data[datatype][0][1].dates != '0') {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					
					dataRow = [data[datatype][i][1].dates, playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = ['Date', 'Name',leaderid.toUpperCase()];
			}
			else {
				for (var i=0;i<data[datatype].length;i++){
					var playerName = (shiohplayers[data[datatype][i][1].stats[0]]) ? shiohplayers[data[datatype][i][1].stats[0]][0] : data[datatype][i][1].stats[0];
					
					dataRow = [playerName,data[datatype][i][0]];
					for (var ii=statse[0];ii<statse[1];ii++) {
						dataRow.push(data[datatype][i][1].stats[ii]);
					}
					myData.push(dataRow);
				}
				baseColumns = ['Name',leaderid.toUpperCase()];
			}	
		}
		
		if (data[datatype][0][1].split.name == 'Day') {
			createCalendar();
		}
		else {
			createLeaderboard();
		}
		d = new Date();
		n = d.getTime();
		console.log('all done:',n);
	  } else {
		console.log('error')
	  }
	}

	request.send();
	
	statDisplay = [4];
	
	//leaderid = leaderid.split('or').join('');
	//leaderid = leaderid.split('and').join('');
	//for (var i=0;i<stats.length-1;i++) {
	//	if (leaderid.indexOf(stats[stats.length-1-i].toLowerCase()) > -1 ) {
	//		statDisplay.push(stats.length-1-i+4);
	//		leaderid = leaderid.split(stats[stats.length-1-i].toLowerCase()).join('');
	//	}
	//}
	//if (statDisplay.length < 6) {
	//	
	//} 
	//console.log(statDisplay);
	d = new Date();
  	n = d.getTime();
  	console.log('d1:',n);
}

function createLeaderboard(displaySplit=[]){
	
	if (borp == 'b' || borp == 'B') {
		stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF'];
	}
	else {
		stats = ['IPouts','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB'];
	}
	columns = [];
	statsCols = [];
	for (var i=0;i<baseColumns.length;i++){
		columns.push(baseColumns[i]);
		statsCols.push(i);
	}
	for (var i=0;i<displayColumns.length;i++){
		columns.push(stats[displayColumns[i]]);
		statsCols.push(displayColumns[i]+baseColumns.length);
	}
	
	showData = [];
	
	splitcol = -1;
	if (baseColumns[1] == 'Year' || baseColumns[1] == 'Age' || baseColumns[1] == 'Team' || baseColumns[1] == 'Opp') {
		splitcol = 1;
		
	}
	else if (baseColumns[0] == 'Year' || baseColumns[0] == 'Age' || baseColumns[0] == 'Team' || baseColumns[0] == 'Opp') {
		splitcol = 0;
	}
	
	if (splitcol > -1 && displaySplit.length == 0) {
		var cYear = 0;
		for (var i=0;i<myData.length;i++) {
			if (myData[i][splitcol] != cYear){
				showData.push(myData[i]);
				cYear = myData[i][splitcol];
			}
		}
		showData.sort(function (a,b) {return b[baseColumns.length-1]-a[baseColumns.length-1];});
	}
	else if (splitcol > -1 && displaySplit.length > 0) {
		for (var i=0;i<myData.length;i++) {
			if (myData[i][splitcol] == displaySplit[0]){
				showData.push(myData[i]);
			}
		}
		showData.sort(function (a,b) {return b[baseColumns.length-1]-a[baseColumns.length-1];});
	}
	else {
		showData = myData;
	}

	if (displaySplit.length == 0) {
    	document.getElementById(datatype).innerHTML = '';
    }
    else {
    	document.getElementById('fullSplits').innerHTML = '';
    }
						
	var table;
	if (displaySplit.length == 0) {
    	table = d3.select('#'+datatype).append('table').attr('class','stats_table');
    }
    else {
    	table = d3.select('#fullSplits').append('table').attr('class','stats_table');
    }
	 
	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id',datatype+'Body');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(showData)
		.enter()
	  .append('tr')
	  .attr('id', function (d,i) {return 'splitrow_'+i;})
	  .on('click', handleClick);

	var cells = rows.selectAll('td')
		.data(function(row) {
			retrow = []; 
			for (var i=0;i<statsCols.length;i++) {
				retrow.push(row[statsCols[i]]);
			} 
			return retrow;
		})
	  .enter()
	.append('td')
	  .text(function (d) { return d});
}

function chgStats(statid) {
	
	for (var i=0;i<displayColumns.length+1;i++) {
		if (i == displayColumns.length) {
			displayColumns.push(statid);
			statcol = document.getElementById('stat'+statid);
			if (statcol.classList.contains('btn-secondary')) { statcol.classList.remove("btn-secondary");	}
			if (statcol.classList.contains('disabled')) { statcol.classList.remove("disabled");	}
			if (!statcol.classList.contains('btn-primary')) { statcol.classList.add("btn-primary");	}

			break;
		}
		if (displayColumns[i] == statid) {
			displayColumns.splice(i, 1);
			statcol = document.getElementById('stat'+statid);
			if (statcol.classList.contains('btn-primary')) { statcol.classList.remove("btn-primary"); console.log(1);	}
			if (!statcol.classList.contains('disabled')) { statcol.classList.add("disabled"); console.log(2);	}
			if (!statcol.classList.contains('btn-secondary')) { statcol.classList.add("btn-secondary"); console.log(3);	}
			
			break;
		}
		else if (displayColumns[i] > statid) {
			displayColumns.splice(i, 0, statid);
			statcol = document.getElementById('stat'+statid);
			if (statcol.classList.contains('btn-secondary')) { statcol.classList.remove("btn-secondary");	}
			if (statcol.classList.contains('disabled')) { statcol.classList.remove("disabled");	}
			if (!statcol.classList.contains('btn-primary')) { statcol.classList.add("btn-primary");	}
			
			break;
		}
	}

	createLeaderboard();
}

function createCalendar() {
	   google.charts.load("current", {packages:["calendar"]});
       google.charts.setOnLoadCallback(drawChart);
	   
}

function drawChart() {
	    if (borp == 'b' || borp == 'B') {
			stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF'];
		}
		else {
			stats = ['IPouts','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB'];
		}
		columns = [];
		statsCols = [];
		for (var i=0;i<baseColumns.length;i++){
			columns.push(baseColumns[i]);
			statsCols.push(i);
		}
		for (var i=0;i<displayColumns.length;i++){
			columns.push(stats[displayColumns[i]]);
			statsCols.push(displayColumns[i]+baseColumns.length);
		}
	
		showData = [];
	
		splitcol = -1;
		if (baseColumns[1] == 'Day') {
			splitcol = 1;
		
		}
		else if (baseColumns[0] == 'Day') {
			splitcol = 0;
		}
	
		if (splitcol > -1 && 0 == 0) {
			var cYear = 0;
			for (var i=0;i<myData.length;i++) {
				if (myData[i][splitcol] != cYear){
					showData.push([new Date(2019,2 + Math.floor((myData[i][splitcol]+10)/31),(10+myData[i][splitcol])%31), parseFloat(myData[i][3]), myData[i][3]+' by '+myData[i][2]+' on '+myData[i][0]]);
					cYear = myData[i][splitcol];
				}
			}
			//showData.sort(function (a,b) {return b[baseColumns.length-1]-a[baseColumns.length-1];});
		}
		//else if (splitcol > -1 && displaySplit.length > 0) {
		//	for (var i=0;i<myData.length;i++) {
		//		if (myData[i][splitcol] == displaySplit[0]){
		//			showData.push(myData[i]);
		//		}
		//	}
		//	showData.sort(function (a,b) {return b[baseColumns.length-1]-a[baseColumns.length-1];});
		//}
		//else {
		//	showData = myData;
		//}
		
	   var dataTable = new google.visualization.DataTable();
       dataTable.addColumn({ type: 'date', id: 'Date' });
       dataTable.addColumn({ type: 'number', id: 'Won/Loss' });
       dataTable.addColumn({ type: 'string', role: 'tooltip' });

       dataTable.addRows(showData);

       var chart = new google.visualization.Calendar(document.getElementById('games'));

       var options = {
         title: "???",
         calendar: { 
         	cellSize: 13,
         	yearLabel: {
				fontName: 'Times-Roman',
				fontSize: 2,
				color: '#FFFFFF'
			},
         },
         
         height: 350,
       };

       chart.draw(dataTable, options);
}

function createCorrels(data) {
	myData = data;
	google.charts.load('current', {'packages':['corechart']});
	google.charts.setOnLoadCallback(drawSeriesChart);

}
function drawSeriesChart() {
	//var dataA = [{"A": 0.264, "PA": 509, "B": 0.292, "name": "aaroh101", "year": 1954}, {"A": 0.333, "PA": 665, "B": 0.293, "name": "aaroh101", "year": 1955}, {"A": 0.334, "PA": 659, "B": 0.323, "name": "aaroh101", "year": 1956}, {"A": 0.312, "PA": 675, "B": 0.333, "name": "aaroh101", "year": 1957}, {"A": 0.319, "PA": 664, "B": 0.331, "name": "aaroh101", "year": 1958}, {"A": 0.365, "PA": 693, "B": 0.342, "name": "aaroh101", "year": 1959}, {"A": 0.321, "PA": 664, "B": 0.265, "name": "aaroh101", "year": 1960}, {"A": 0.346, "PA": 671, "B": 0.307, "name": "aaroh101", "year": 1961}, {"A": 0.319, "PA": 667, "B": 0.326, "name": "aaroh101", "year": 1962}, {"A": 0.31, "PA": 714, "B": 0.326, "name": "aaroh101", "year": 1963}, {"A": 0.322, "PA": 634, "B": 0.334, "name": "aaroh101", "year": 1964}, {"A": 0.302, "PA": 639, "B": 0.334, "name": "aaroh101", "year": 1965}, {"A": 0.268, "PA": 687, "B": 0.289, "name": "aaroh101", "year": 1966}, {"A": 0.301, "PA": 669, "B": 0.312, "name": "aaroh101", "year": 1967}, {"A": 0.265, "PA": 676, "B": 0.305, "name": "aaroh101", "year": 1968}, {"A": 0.283, "PA": 639, "B": 0.317, "name": "aaroh101", "year": 1969}, {"A": 0.282, "PA": 598, "B": 0.316, "name": "aaroh101", "year": 1970}, {"A": 0.36, "PA": 573, "B": 0.3, "name": "aaroh101", "year": 1971}, {"A": 0.256, "PA": 545, "B": 0.272, "name": "aaroh101", "year": 1972}, {"A": 0.308, "PA": 465, "B": 0.293, "name": "aaroh101", "year": 1973}, {"A": 0.272, "PA": 382, "B": 0.262, "name": "aaroh101", "year": 1974}, {"A": 0.236, "PA": 543, "B": 0.232, "name": "aaroh101", "year": 1975}, {"A": 0.269, "PA": 308, "B": 0.191, "name": "aaroh101", "year": 1976}, {"A": 0.238, "PA": 382, "B": 0.222, "name": "aarot101", "year": 1962}, {"A": 0.257, "PA": 308, "B": 0.232, "name": "aarot101", "year": 1968}, {"A": 0.326, "PA": 261, "B": 0.216, "name": "abboj002", "year": 1998}, {"A": 0.287, "PA": 242, "B": 0.261, "name": "abboj002", "year": 2000}, {"A": 0.261, "PA": 371, "B": 0.239, "name": "abbok002", "year": 1994}, {"A": 0.229, "PA": 467, "B": 0.277, "name": "abbok002", "year": 1995}, {"A": 0.243, "PA": 349, "B": 0.261, "name": "abbok002", "year": 1996}, {"A": 0.274, "PA": 273, "B": 0.273, "name": "abbok002", "year": 1997}, {"A": 0.276, "PA": 212, "B": 0.25, "name": "abbok002", "year": 1998}, {"A": 0.243, "PA": 305, "B": 0.293, "name": "abbok002", "year": 1999}, {"A": 0.305, "PA": 335, "B": 0.233, "name": "aberb001", "year": 2001}, {"A": 0.246, "PA": 504, "B": 0.236, "name": "aberb001", "year": 2002}, {"A": 0.243, "PA": 281, "B": 0.185, "name": "aberr001", "year": 2006}, {"A": 0.17, "PA": 230, "B": 0.215, "name": "abnes001", "year": 1991}, {"A": 0.287, "PA": 512, "B": 0.282, "name": "abrac101", "year": 1953}, {"A": 0.308, "PA": 559, "B": 0.251, "name": "abrac101", "year": 1954}, {"A": 0.217, "PA": 406, "B": 0.265, "name": "abrac101", "year": 1955}, {"A": 0.263, "PA": 210, "B": 0.236, "name": "abreb001", "year": 1997}, {"A": 0.31, "PA": 589, "B": 0.312, "name": "abreb001", "year": 1998}, {"A": 0.368, "PA": 662, "B": 0.305, "name": "abreb001", "year": 1999}, {"A": 0.342, "PA": 680, "B": 0.288, "name": "abreb001", "year": 2000}, {"A": 0.291, "PA": 704, "B": 0.287, "name": "abreb001", "year": 2001}, {"A": 0.321, "PA": 685, "B": 0.295, "name": "abreb001", "year": 2002}, {"A": 0.271, "PA": 695, "B": 0.328, "name": "abreb001", "year": 2003}, {"A": 0.302, "PA": 713, "B": 0.3, "name": "abreb001", "year": 2004}, {"A": 0.288, "PA": 718, "B": 0.284, "name": "abreb001", "year": 2005}, {"A": 0.271, "PA": 686, "B": 0.322, "name": "abreb001", "year": 2006}, {"A": 0.293, "PA": 699, "B": 0.272, "name": "abreb001", "year": 2007}, {"A": 0.304, "PA": 684, "B": 0.287, "name": "abreb001", "year": 2008}, {"A": 0.328, "PA": 667, "B": 0.256, "name": "abreb001", "year": 2009}, {"A": 0.255, "PA": 667, "B": 0.254, "name": "abreb001", "year": 2010}, {"A": 0.273, "PA": 585, "B": 0.231, "name": "abreb001", "year": 2011}, {"A": 0.28, "PA": 257, "B": 0.205, "name": "abreb001", "year": 2012}, {"A": 0.249, "PA": 622, "B": 0.381, "name": "abrej003", "year": 2014}, {"A": 0.29, "PA": 668, "B": 0.289, "name": "abrej003", "year": 2015}, {"A": 0.323, "PA": 695, "B": 0.268, "name": "abrej003", "year": 2016}, {"A": 0.293, "PA": 674, "B": 0.316, "name": "abrej003", "year": 2017}, {"A": 0.25, "PA": 553, "B": 0.279, "name": "abrej003", "year": 2018}, {"A": 0.281, "PA": 376, "B": 0.265, "name": "ackld001", "year": 2011}, {"A": 0.241, "PA": 668, "B": 0.209, "name": "ackld001", "year": 2012}, {"A": 0.254, "PA": 427, "B": 0.251, "name": "ackld001", "year": 2013}, {"A": 0.219, "PA": 542, "B": 0.27, "name": "ackld001", "year": 2014}, {"A": 0.222, "PA": 264, "B": 0.241, "name": "ackld001", "year": 2015}, {"A": 0.32, "PA": 487, "B": 0.264, "name": "acunr001", "year": 2018}, {"A": 0.261, "PA": 428, "B": 0.267, "name": "adaij101", "year": 1961}, {"A": 0.324, "PA": 573, "B": 0.246, "name": "adaij101", "year": 1962}, {"A": 0.219, "PA": 401, "B": 0.237, "name": "adaij101", "year": 1963}, {"A": 0.243, "PA": 605, "B": 0.251, "name": "adaij101", "year": 1964}, {"A": 0.257, "PA": 625, "B": 0.261, "name": "adaij101", "year": 1965}, {"A": 0.228, "PA": 460, "B": 0.269, "name": "adaij101", "year": 1966}, {"A": 0.27, "PA": 443, "B": 0.27, "name": "adaij101", "year": 1967}, {"A": 0.197, "PA": 224, "B": 0.232, "name": "adaij101", "year": 1968}, {"A": 0.281, "PA": 461, "B": 0.216, "name": "adaij101", "year": 1969}, {"A": 0.271, "PA": 485, "B": 0.225, "name": "adamb101", "year": 1943}, {"A": 0.303, "PA": 682, "B": 0.26, "name": "adamb101", "year": 1944}, {"A": 0.302, "PA": 708, "B": 0.27, "name": "adamb101", "year": 1945}, {"A": 0.228, "PA": 346, "B": 0.261, "name": "adamb103", "year": 1946}, {"A": 0.281, "PA": 253, "B": 0.263, "name": "adamb103", "year": 1947}, {"A": 0.307, "PA": 294, "B": 0.281, "name": "adamb103", "year": 1948}, {"A": 0.237, "PA": 307, "B": 0.27, "name": "adamb103", "year": 1949}, {"A": 0.257, "PA": 394, "B": 0.318, "name": "adamb103", "year": 1950}, {"A": 0.276, "PA": 450, "B": 0.253, "name": "adamb103", "year": 1951}, {"A": 0.268, "PA": 694, "B": 0.297, "name": "adamb103", "year": 1952}, {"A": 0.268, "PA": 678, "B": 0.28, "name": "adamb103", "year": 1953}, {"A": 0.226, "PA": 454, "B": 0.304, "name": "adamb103", "year": 1954}, {"A": 0.247, "PA": 211, "B": 0.252, "name": "adamb103", "year": 1957}, {"A": 0.175, "PA": 256, "B": 0.261, "name": "adamc001", "year": 2016}, {"A": 0.351, "PA": 290, "B": 0.329, "name": "adamg101", "year": 1977}, {"A": 0.282, "PA": 332, "B": 0.238, "name": "adamg101", "year": 1978}, {"A": 0.283, "PA": 362, "B": 0.318, "name": "adamg101", "year": 1979}, {"A": 0.306, "PA": 287, "B": 0.264, "name": "adamg101", "year": 1980}, {"A": 0.261, "PA": 243, "B": 0.159, "name": "adamg101", "year": 1981}, {"A": 0.253, "PA": 319, "B": 0.315, "name": "adamm002", "year": 2013}, {"A": 0.285, "PA": 563, "B": 0.291, "name": "adamm002", "year": 2014}, {"A": 0.26, "PA": 327, "B": 0.238, "name": "adamm002", "year": 2016}, {"A": 0.258, "PA": 367, "B": 0.292, "name": "adamm002", "year": 2017}, {"A": 0.195, "PA": 337, "B": 0.273, "name": "adamm002", "year": 2018}, {"A": 0.264, "PA": 544, "B": 0.249, "name": "adamr002", "year": 2005}, {"A": 0.194, "PA": 280, "B": 0.239, "name": "adamr002", "year": 2006}, {"A": 0.266, "PA": 352, "B": 0.31, "name": "adams101", "year": 1923}, {"A": 0.316, "PA": 474, "B": 0.24, "name": "adams101", "year": 1924}, {"A": 0.286, "PA": 687, "B": 0.287, "name": "adams101", "year": 1925}, {"A": 0.288, "PA": 701, "B": 0.329, "name": "adams101", "year": 1926}, {"A": 0.316, "PA": 705, "B": 0.266, "name": "adams101", "year": 1927}, {"A": 0.262, "PA": 628, "B": 0.292, "name": "adams101", "year": 1928}, {"A": 0.252, "PA": 217, "B": 0.268, "name": "adams101", "year": 1929}, {"A": 0.317, "PA": 629, "B": 0.309, "name": "adams101", "year": 1930}, {"A": 0.313, "PA": 658, "B": 0.27, "name": "adams101", "year": 1931}, {"A": 0.264, "PA": 632, "B": 0.248, "name": "adams101", "year": 1933}, {"A": 0.213, "PA": 301, "B": 0.294, "name": "adams101", "year": 1934}, {"A": 0.28, "PA": 296, "B": 0.248, "name": "adams102", "year": 1927}, {"A": 0.296, "PA": 323, "B": 0.257, "name": "adamw002", "year": 2018}, {"A": 0.296, "PA": 398, "B": 0.288, "name": "adcoj101", "year": 1950}, {"A": 0.237, "PA": 422, "B": 0.248, "name": "adcoj101", "year": 1951}, {"A": 0.26, "PA": 403, "B": 0.294, "name": "adcoj101", "year": 1952}, {"A": 0.29, "PA": 641, "B": 0.276, "name": "adcoj101", "year": 1953}, {"A": 0.293, "PA": 562, "B": 0.317, "name": "adcoj101", "year": 1954}, {"A": 0.197, "PA": 324, "B": 0.343, "name": "adcoj101", "year": 1955}, {"A": 0.335, "PA": 501, "B": 0.258, "name": "adcoj101", "year": 1956}, {"A": 0.214, "PA": 231, "B": 0.371, "name": "adcoj101", "year": 1957}, {"A": 0.244, "PA": 349, "B": 0.299, "name": "adcoj101", "year": 1958}, {"A": 0.252, "PA": 444, "B": 0.328, "name": "adcoj101", "year": 1959}, {"A": 0.306, "PA": 570, "B": 0.288, "name": "adcoj101", "year": 1960}, {"A": 0.321, "PA": 629, "B": 0.249, "name": "adcoj101", "year": 1961}, {"A": 0.234, "PA": 447, "B": 0.262, "name": "adcoj101", "year": 1962}, {"A": 0.282, "PA": 317, "B": 0.213, "name": "adcoj101", "year": 1963}, {"A": 0.243, "PA": 415, "B": 0.285, "name": "adcoj101", "year": 1964}, {"A": 0.222, "PA": 386, "B": 0.26, "name": "adcoj101", "year": 1965}, {"A": 0.267, "PA": 265, "B": 0.278, "name": "adcoj101", "year": 1966}, {"A": 0.276, "PA": 317, "B": 0.312, "name": "addib101", "year": 1952}, {"A": 0.25, "PA": 366, "B": 0.251, "name": "adrie001", "year": 2018}, {"A": 0.275, "PA": 314, "B": 0.299, "name": "agbab001", "year": 1999}, {"A": 0.263, "PA": 415, "B": 0.318, "name": "agbab001", "year": 2000}, {"A": 0.242, "PA": 339, "B": 0.316, "name": "agbab001", "year": 2001}, {"A": 0.272, "PA": 689, "B": 0.274, "name": "ageet101", "year": 1966}, {"A": 0.252, "PA": 584, "B": 0.21, "name": "ageet101", "year": 1967}, {"A": 0.209, "PA": 391, "B": 0.227, "name": "ageet101", "year": 1968}, {"A": 0.296, "PA": 635, "B": 0.245, "name": "ageet101", "year": 1969}, {"A": 0.301, "PA": 696, "B": 0.27, "name": "ageet101", "year": 1970}, {"A": 0.28, "PA": 482, "B": 0.288, "name": "ageet101", "year": 1971}, {"A": 0.213, "PA": 483, "B": 0.24, "name": "ageet101", "year": 1972}, {"A": 0.198, "PA": 288, "B": 0.246, "name": "ageet101", "year": 1973}, {"A": 0.255, "PA": 491, "B": 0.247, "name": "aggah101", "year": 1954}, {"A": 0.173, "PA": 234, "B": 0.234, "name": "agual001", "year": 1987}, {"A": 0.228, "PA": 260, "B": 0.268, "name": "agual001", "year": 1988}, {"A": 0.203, "PA": 311, "B": 0.317, "name": "aguij001", "year": 2017}, {"A": 0.29, "PA": 566, "B": 0.259, "name": "aguij001", "year": 2018}, {"A": 0.216, "PA": 459, "B": 0.233, "name": "ahmen001", "year": 2015}, {"A": 0.222, "PA": 308, "B": 0.213, "name": "ahmen001", "year": 2016}, {"A": 0.259, "PA": 564, "B": 0.207, "name": "ahmen001", "year": 2018}, {"A": 0.297, "PA": 447, "B": 0.265, "name": "aikew001", "year": 1979}, {"A": 0.276, "PA": 623, "B": 0.28, "name": "aikew001", "year": 1980}, {"A": 0.261, "PA": 419, "B": 0.271, "name": "aikew001", "year": 1981}, {"A": 0.248, "PA": 519, "B": 0.309, "name": "aikew001", "year": 1982}, {"A": 0.292, "PA": 458, "B": 0.311, "name": "aikew001", "year": 1983}, {"A": 0.2, "PA": 265, "B": 0.208, "name": "aikew001", "year": 1984}, {"A": 0.206, "PA": 331, "B": 0.263, "name": "aingd101", "year": 1979}, {"A": 0.159, "PA": 275, "B": 0.21, "name": "aingd101", "year": 1981}, {"A": 0.225, "PA": 209, "B": 0.231, "name": "ainse101", "year": 1920}, {"A": 0.316, "PA": 419, "B": 0.266, "name": "ainse101", "year": 1922}, {"A": 0.162, "PA": 306, "B": 0.25, "name": "ainse101", "year": 1923}, {"A": 0.236, "PA": 277, "B": 0.317, "name": "akerb101", "year": 1930}, {"A": 0.268, "PA": 244, "B": 0.302, "name": "albio001", "year": 2017}, {"A": 0.261, "PA": 684, "B": 0.261, "name": "albio001", "year": 2018}, {"A": 0.219, "PA": 300, "B": 0.191, "name": "alcaa001", "year": 2014}, {"A": 0.259, "PA": 255, "B": 0.242, "name": "aldrm001", "year": 1986}, {"A": 0.319, "PA": 406, "B": 0.331, "name": "aldrm001", "year": 1987}, {"A": 0.259, "PA": 449, "B": 0.275, "name": "aldrm001", "year": 1988}, {"A": 0.23, "PA": 239, "B": 0.257, "name": "aldrm001", "year": 1991}, {"A": 0.232, "PA": 292, "B": 0.3, "name": "aldrm001", "year": 1993}, {"A": 0.358, "PA": 701, "B": 0.326, "name": "alexd101", "year": 1929}, {"A": 0.342, "PA": 660, "B": 0.308, "name": "alexd101", "year": 1930}, {"A": 0.331, "PA": 583, "B": 0.318, "name": "alexd101", "year": 1931}, {"A": 0.357, "PA": 454, "B": 0.376, "name": "alexd101", "year": 1932}, {"A": 0.24, "PA": 338, "B": 0.322, "name": "alexd101", "year": 1933}, {"A": 0.222, "PA": 564, "B": 0.226, "name": "alexg101", "year": 1978}, {"A": 0.233, "PA": 415, "B": 0.224, "name": "alexg101", "year": 1979}, {"A": 0.229, "PA": 267, "B": 0.245, "name": "alexm001", "year": 1995}, {"A": 0.278, "PA": 272, "B": 0.255, "name": "alexm001", "year": 1997}, {"A": 0.219, "PA": 289, "B": 0.232, "name": "alexm001", "year": 1998}, {"A": 0.224, "PA": 377, "B": 0.292, "name": "alfaj002", "year": 2018}, {"A": 0.264, "PA": 356, "B": 0.291, "name": "alfoe001", "year": 1995}, {"A": 0.256, "PA": 407, "B": 0.264, "name": "alfoe001", "year": 1996}, {"A": 0.322, "PA": 599, "B": 0.308, "name": "alfoe001", "year": 1997}, {"A": 0.249, "PA": 630, "B": 0.31, "name": "alfoe001", "year": 1998}, {"A": 0.302, "PA": 726, "B": 0.305, "name": "alfoe001", "year": 1999}, {"A": 0.354, "PA": 650, "B": 0.292, "name": "alfoe001", "year": 2000}, {"A": 0.264, "PA": 519, "B": 0.222, "name": "alfoe001", "year": 2001}, {"A": 0.294, "PA": 562, "B": 0.318, "name": "alfoe001", "year": 2002}, {"A": 0.252, "PA": 586, "B": 0.264, "name": "alfoe001", "year": 2003}, {"A": 0.27, "PA": 576, "B": 0.308, "name": "alfoe001", "year": 2004}, {"A": 0.306, "PA": 402, "B": 0.245, "name": "alfoe001", "year": 2005}, {"A": 0.222, "PA": 309, "B": 0.3, "name": "alfoe002", "year": 2006}, {"A": 0.202, "PA": 330, "B": 0.219, "name": "alicl001", "year": 1988}, {"A": 0.188, "PA": 302, "B": 0.297, "name": "alicl001", "year": 1992}, {"A": 0.278, "PA": 421, "B": 0.279, "name": "alicl001", "year": 1993}, {"A": 0.275, "PA": 242, "B": 0.28, "name": "alicl001", "year": 1994}, {"A": 0.271, "PA": 510, "B": 0.267, "name": "alicl001", "year": 1995}, {"A": 0.265, "PA": 446, "B": 0.252, "name": "alicl001", "year": 1996}, {"A": 0.272, "PA": 471, "B": 0.237, "name": "alicl001", "year": 1997}, {"A": 0.235, "PA": 308, "B": 0.304, "name": "alicl001", "year": 1998}, {"A": 0.279, "PA": 619, "B": 0.308, "name": "alicl001", "year": 2000}, {"A": 0.284, "PA": 418, "B": 0.263, "name": "alicl001", "year": 2001}, {"A": 0.212, "PA": 273, "B": 0.241, "name": "alicl001", "year": 2002}, {"A": 0.212, "PA": 324, "B": 0.238, "name": "allaa001", "year": 1986}, {"A": 0.29, "PA": 474, "B": 0.238, "name": "allaa001", "year": 1988}, {"A": 0.24, "PA": 359, "B": 0.225, "name": "allaa001", "year": 1989}, {"A": 0.281, "PA": 646, "B": 0.256, "name": "alleb105", "year": 1962}, {"A": 0.263, "PA": 466, "B": 0.216, "name": "alleb105", "year": 1963}, {"A": 0.252, "PA": 281, "B": 0.177, "name": "alleb105", "year": 1964}, {"A": 0.27, "PA": 350, "B": 0.206, "name": "alleb105", "year": 1966}, {"A": 0.213, "PA": 279, "B": 0.17, "name": "alleb105", "year": 1967}, {"A": 0.238, "PA": 405, "B": 0.243, "name": "alleb105", "year": 1968}, {"A": 0.22, "PA": 417, "B": 0.273, "name": "alleb105", "year": 1969}, {"A": 0.22, "PA": 305, "B": 0.246, "name": "alleb105", "year": 1970}, {"A": 0.25, "PA": 262, "B": 0.28, "name": "alleb105", "year": 1971}, {"A": 0.271, "PA": 248, "B": 0.185, "name": "alleb105", "year": 1972}, {"A": 0.308, "PA": 523, "B": 0.244, "name": "allec001", "year": 1999}, {"A": 0.292, "PA": 709, "B": 0.343, "name": "alled101", "year": 1964}, {"A": 0.3, "PA": 706, "B": 0.304, "name": "alled101", "year": 1965}, {"A": 0.302, "PA": 599, "B": 0.329, "name": "alled101", "year": 1966}, {"A": 0.317, "PA": 540, "B": 0.295, "name": "alled101", "year": 1967}, {"A": 0.277, "PA": 605, "B": 0.25, "name": "alled101", "year": 1968}, {"A": 0.304, "PA": 506, "B": 0.272, "name": "alled101", "year": 1969}, {"A": 0.278, "PA": 533, "B": 0.278, "name": "alled101", "year": 1970}, {"A": 0.289, "PA": 649, "B": 0.3, "name": "alled101", "year": 1971}, {"A": 0.323, "PA": 609, "B": 0.292, "name": "alled101", "year": 1972}, {"A": 0.296, "PA": 288, "B": 0.339, "name": "alled101", "year": 1973}, {"A": 0.319, "PA": 525, "B": 0.284, "name": "alled101", "year": 1974}, {"A": 0.234, "PA": 481, "B": 0.232, "name": "alled101", "year": 1975}, {"A": 0.256, "PA": 339, "B": 0.281, "name": "alled101", "year": 1976}, {"A": 0.268, "PA": 388, "B": 0.317, "name": "allee101", "year": 1927}, {"A": 0.344, "PA": 527, "B": 0.263, "name": "allee101", "year": 1928}, {"A": 0.328, "PA": 568, "B": 0.259, "name": "allee101", "year": 1929}, {"A": 0.261, "PA": 311, "B": 0.316, "name": "allee101", "year": 1930}, {"A": 0.375, "PA": 321, "B": 0.272, "name": "allee101", "year": 1931}, {"A": 0.242, "PA": 280, "B": 0.242, "name": "allee101", "year": 1933}, {"A": 0.365, "PA": 633, "B": 0.291, "name": "allee101", "year": 1934}, {"A": 0.287, "PA": 700, "B": 0.324, "name": "allee101", "year": 1935}, {"A": 0.274, "PA": 531, "B": 0.31, "name": "allee101", "year": 1936}, {"A": 0.319, "PA": 349, "B": 0.306, "name": "allee101", "year": 1937}, {"A": 0.2, "PA": 271, "B": 0.204, "name": "alleg001", "year": 1979}, {"A": 0.236, "PA": 307, "B": 0.166, "name": "alleg001", "year": 1982}, {"A": 0.242, "PA": 269, "B": 0.219, "name": "alleg001", "year": 1983}, {"A": 0.227, "PA": 291, "B": 0.286, "name": "alleg002", "year": 2018}, {"A": 0.216, "PA": 234, "B": 0.205, "name": "alleg101", "year": 1964}, {"A": 0.244, "PA": 540, "B": 0.26, "name": "alleg101", "year": 1965}, {"A": 0.32, "PA": 634, "B": 0.278, "name": "alleg101", "year": 1966}, {"A": 0.242, "PA": 604, "B": 0.33, "name": "alleg101", "year": 1967}, {"A": 0.225, "PA": 530, "B": 0.265, "name": "alleg101", "year": 1968}, {"A": 0.222, "PA": 309, "B": 0.27, "name": "alleg101", "year": 1969}, {"A": 0.237, "PA": 466, "B": 0.251, "name": "alleg101", "year": 1970}, {"A": 0.238, "PA": 389, "B": 0.215, "name": "alleg101", "year": 1971}, {"A": 0.241, "PA": 389, "B": 0.252, "name": "alleg101", "year": 1972}, {"A": 0.277, "PA": 308, "B": 0.189, "name": "alleh104", "year": 1967}, {"A": 0.278, "PA": 285, "B": 0.277, "name": "alleh104", "year": 1969}, {"A": 0.197, "PA": 259, "B": 0.31, "name": "allej001", "year": 1996}, {"A": 0.207, "PA": 435, "B": 0.298, "name": "allej001", "year": 1997}, {"A": 0.237, "PA": 409, "B": 0.306, "name": "allej001", "year": 1998}, {"A": 0.204, "PA": 313, "B": 0.241, "name": "allej101", "year": 1983}, {"A": 0.247, "PA": 638, "B": 0.273, "name": "allib103", "year": 1959}, {"A": 0.284, "PA": 605, "B": 0.219, "name": "allib103", "year": 1960}, {"A": 0.2, "PA": 676, "B": 0.294, "name": "allib103", "year": 1961}, {"A": 0.254, "PA": 613, "B": 0.276, "name": "allib103", "year": 1962}, {"A": 0.274, "PA": 626, "B": 0.268, "name": "allib103", "year": 1963}, {"A": 0.324, "PA": 594, "B": 0.246, "name": "allib103", "year": 1964}, {"A": 0.207, "PA": 519, "B": 0.26, "name": "allib103", "year": 1965}, {"A": 0.219, "PA": 576, "B": 0.298, "name": "allib103", "year": 1967}, {"A": 0.219, "PA": 527, "B": 0.274, "name": "allib103", "year": 1968}, {"A": 0.268, "PA": 220, "B": 0.187, "name": "allib103", "year": 1969}, {"A": 0.171, "PA": 482, "B": 0.222, "name": "allig101", "year": 1954}, {"A": 0.293, "PA": 673, "B": 0.284, "name": "almam101", "year": 1935}, {"A": 0.23, "PA": 347, "B": 0.272, "name": "almam101", "year": 1936}, {"A": 0.29, "PA": 604, "B": 0.297, "name": "almam101", "year": 1937}, {"A": 0.313, "PA": 689, "B": 0.306, "name": "almam101", "year": 1938}, {"A": 0.212, "PA": 267, "B": 0.241, "name": "almam101", "year": 1939}, {"A": 0.286, "PA": 258, "B": 0.213, "name": "almoa001", "year": 2015}, {"A": 0.296, "PA": 322, "B": 0.301, "name": "almoa002", "year": 2017}, {"A": 0.285, "PA": 479, "B": 0.286, "name": "almoa002", "year": 2018}, {"A": 0.248, "PA": 670, "B": 0.273, "name": "almob001", "year": 1977}, {"A": 0.274, "PA": 442, "B": 0.232, "name": "almob001", "year": 1978}, {"A": 0.305, "PA": 226, "B": 0.133, "name": "almob001", "year": 1979}, {"A": 0.275, "PA": 377, "B": 0.322, "name": "almob001", "year": 1981}, {"A": 0.245, "PA": 336, "B": 0.267, "name": "almob001", "year": 1982}, {"A": 0.283, "PA": 495, "B": 0.247, "name": "almob001", "year": 1983}, {"A": 0.233, "PA": 225, "B": 0.212, "name": "almob001", "year": 1984}, {"A": 0.229, "PA": 274, "B": 0.311, "name": "almob001", "year": 1985}, {"A": 0.186, "PA": 230, "B": 0.255, "name": "almob001", "year": 1986}, {"A": 0.229, "PA": 611, "B": 0.303, "name": "alomr001", "year": 1988}, {"A": 0.291, "PA": 702, "B": 0.297, "name": "alomr001", "year": 1989}, {"A": 0.286, "PA": 646, "B": 0.286, "name": "alomr001", "year": 1990}, {"A": 0.285, "PA": 719, "B": 0.303, "name": "alomr001", "year": 1991}, {"A": 0.29, "PA": 671, "B": 0.332, "name": "alomr001", "year": 1992}, {"A": 0.339, "PA": 682, "B": 0.314, "name": "alomr001", "year": 1993}, {"A": 0.298, "PA": 455, "B": 0.313, "name": "alomr001", "year": 1994}, {"A": 0.283, "PA": 577, "B": 0.317, "name": "alomr001", "year": 1995}, {"A": 0.334, "PA": 699, "B": 0.322, "name": "alomr001", "year": 1996}, {"A": 0.347, "PA": 469, "B": 0.316, "name": "alomr001", "year": 1997}, {"A": 0.289, "PA": 657, "B": 0.275, "name": "alomr001", "year": 1998}, {"A": 0.333, "PA": 694, "B": 0.313, "name": "alomr001", "year": 1999}, {"A": 0.287, "PA": 697, "B": 0.332, "name": "alomr001", "year": 2000}, {"A": 0.338, "PA": 677, "B": 0.332, "name": "alomr001", "year": 2001}, {"A": 0.289, "PA": 655, "B": 0.246, "name": "alomr001", "year": 2002}, {"A": 0.275, "PA": 597, "B": 0.239, "name": "alomr001", "year": 2003}, {"A": 0.265, "PA": 483, "B": 0.309, "name": "aloms001", "year": 1990}, {"A": 0.228, "PA": 320, "B": 0.278, "name": "aloms001", "year": 1992}, {"A": 0.295, "PA": 237, "B": 0.247, "name": "aloms001", "year": 1993}, {"A": 0.309, "PA": 320, "B": 0.266, "name": "aloms001", "year": 1994}, {"A": 0.228, "PA": 444, "B": 0.301, "name": "aloms001", "year": 1996}, {"A": 0.327, "PA": 480, "B": 0.318, "name": "aloms001", "year": 1997}, {"A": 0.228, "PA": 438, "B": 0.242, "name": "aloms001", "year": 1998}, {"A": 0.248, "PA": 384, "B": 0.324, "name": "aloms001", "year": 2000}, {"A": 0.277, "PA": 239, "B": 0.207, "name": "aloms001", "year": 2001}, {"A": 0.313, "PA": 296, "B": 0.238, "name": "aloms001", "year": 2002}, {"A": 0.219, "PA": 395, "B": 0.286, "name": "aloms101", "year": 1968}, {"A": 0.216, "PA": 662, "B": 0.278, "name": "aloms101", "year": 1969}, {"A": 0.274, "PA": 735, "B": 0.229, "name": "aloms101", "year": 1970}, {"A": 0.211, "PA": 738, "B": 0.305, "name": "aloms101", "year": 1971}, {"A": 0.251, "PA": 665, "B": 0.228, "name": "aloms101", "year": 1972}, {"A": 0.23, "PA": 519, "B": 0.244, "name": "aloms101", "year": 1973}, {"A": 0.253, "PA": 356, "B": 0.269, "name": "aloms101", "year": 1974}, {"A": 0.229, "PA": 528, "B": 0.247, "name": "aloms101", "year": 1975}, {"A": 0.282, "PA": 619, "B": 0.263, "name": "alony001", "year": 2012}, {"A": 0.253, "PA": 375, "B": 0.309, "name": "alony001", "year": 2013}, {"A": 0.202, "PA": 288, "B": 0.282, "name": "alony001", "year": 2014}, {"A": 0.289, "PA": 402, "B": 0.276, "name": "alony001", "year": 2015}, {"A": 0.244, "PA": 532, "B": 0.261, "name": "alony001", "year": 2016}, {"A": 0.276, "PA": 520, "B": 0.256, "name": "alony001", "year": 2017}, {"A": 0.245, "PA": 574, "B": 0.255, "name": "alony001", "year": 2018}, {"A": 0.292, "PA": 268, "B": 0.256, "name": "alouf101", "year": 1959}, {"A": 0.279, "PA": 347, "B": 0.248, "name": "alouf101", "year": 1960}, {"A": 0.271, "PA": 447, "B": 0.305, "name": "alouf101", "year": 1961}, {"A": 0.31, "PA": 605, "B": 0.32, "name": "alouf101", "year": 1962}, {"A": 0.269, "PA": 607, "B": 0.291, "name": "alouf101", "year": 1963}, {"A": 0.246, "PA": 455, "B": 0.258, "name": "alouf101", "year": 1964}, {"A": 0.262, "PA": 599, "B": 0.332, "name": "alouf101", "year": 1965}, {"A": 0.344, "PA": 706, "B": 0.309, "name": "alouf101", "year": 1966}, {"A": 0.268, "PA": 617, "B": 0.278, "name": "alouf101", "year": 1967}, {"A": 0.328, "PA": 718, "B": 0.307, "name": "alouf101", "year": 1968}, {"A": 0.275, "PA": 509, "B": 0.285, "name": "alouf101", "year": 1969}, {"A": 0.222, "PA": 618, "B": 0.315, "name": "alouf101", "year": 1970}, {"A": 0.251, "PA": 509, "B": 0.315, "name": "alouf101", "year": 1971}, {"A": 0.256, "PA": 351, "B": 0.294, "name": "alouf101", "year": 1972}, {"A": 0.234, "PA": 343, "B": 0.227, "name": "alouf101", "year": 1973}, {"A": 0.274, "PA": 398, "B": 0.273, "name": "alouj101", "year": 1964}, {"A": 0.317, "PA": 567, "B": 0.276, "name": "alouj101", "year": 1965}, {"A": 0.242, "PA": 387, "B": 0.274, "name": "alouj101", "year": 1966}, {"A": 0.28, "PA": 534, "B": 0.304, "name": "alouj101", "year": 1967}, {"A": 0.301, "PA": 436, "B": 0.22, "name": "alouj101", "year": 1968}, {"A": 0.24, "PA": 476, "B": 0.254, "name": "alouj101", "year": 1969}, {"A": 0.308, "PA": 487, "B": 0.303, "name": "alouj101", "year": 1970}, {"A": 0.283, "PA": 455, "B": 0.275, "name": "alouj101", "year": 1971}, {"A": 0.275, "PA": 231, "B": 0.263, "name": "alouj101", "year": 1974}, {"A": 0.273, "PA": 377, "B": 0.289, "name": "aloum001", "year": 1992}, {"A": 0.288, "PA": 536, "B": 0.283, "name": "aloum001", "year": 1993}, {"A": 0.316, "PA": 470, "B": 0.363, "name": "aloum001", "year": 1994}, {"A": 0.287, "PA": 386, "B": 0.259, "name": "aloum001", "year": 1995}, {"A": 0.276, "PA": 597, "B": 0.286, "name": "aloum001", "year": 1996}, {"A": 0.287, "PA": 617, "B": 0.297, "name": "aloum001", "year": 1997}, {"A": 0.315, "PA": 679, "B": 0.307, "name": "aloum001", "year": 1998}, {"A": 0.354, "PA": 517, "B": 0.354, "name": "aloum001", "year": 2000}, {"A": 0.362, "PA": 581, "B": 0.301, "name": "aloum001", "year": 2001}, {"A": 0.306, "PA": 533, "B": 0.241, "name": "aloum001", "year": 2002}, {"A": 0.263, "PA": 638, "B": 0.293, "name": "aloum001", "year": 2003}, {"A": 0.272, "PA": 675, "B": 0.312, "name": "aloum001", "year": 2004}, {"A": 0.314, "PA": 490, "B": 0.327, "name": "aloum001", "year": 2005}, {"A": 0.369, "PA": 378, "B": 0.232, "name": "aloum001", "year": 2006}, {"A": 0.348, "PA": 360, "B": 0.335, "name": "aloum001", "year": 2007}, {"A": 0.309, "PA": 217, "B": 0.31, "name": "aloum101", "year": 1961}, {"A": 0.233, "PA": 267, "B": 0.286, "name": "aloum101", "year": 1964}, {"A": 0.252, "PA": 351, "B": 0.207, "name": "aloum101", "year": 1965}, {"A": 0.318, "PA": 578, "B": 0.362, "name": "aloum101", "year": 1966}, {"A": 0.351, "PA": 583, "B": 0.326, "name": "aloum101", "year": 1967}, {"A": 0.335, "PA": 596, "B": 0.329, "name": "aloum101", "year": 1968}, {"A": 0.313, "PA": 746, "B": 0.35, "name": "aloum101", "year": 1969}, {"A": 0.294, "PA": 718, "B": 0.3, "name": "aloum101", "year": 1970}, {"A": 0.295, "PA": 660, "B": 0.331, "name": "aloum101", "year": 1971}, {"A": 0.29, "PA": 567, "B": 0.319, "name": "aloum101", "year": 1972}, {"A": 0.316, "PA": 550, "B": 0.276, "name": "aloum101", "year": 1973}, {"A": 0.29, "PA": 271, "B": 0.215, "name": "alstt101", "year": 1954}, {"A": 0.254, "PA": 227, "B": 0.135, "name": "altha001", "year": 2016}, {"A": 0.274, "PA": 412, "B": 0.268, "name": "altha001", "year": 2017}, {"A": 0.219, "PA": 285, "B": 0.152, "name": "altha001", "year": 2018}, {"A": 0.231, "PA": 467, "B": 0.258, "name": "altmg101", "year": 1959}, {"A": 0.267, "PA": 373, "B": 0.265, "name": "altmg101", "year": 1960}, {"A": 0.333, "PA": 573, "B": 0.271, "name": "altmg101", "year": 1961}, {"A": 0.326, "PA": 603, "B": 0.31, "name": "altmg101", "year": 1962}, {"A": 0.238, "PA": 521, "B": 0.316, "name": "altmg101", "year": 1963}, {"A": 0.243, "PA": 445, "B": 0.215, "name": "altmg101", "year": 1964}, {"A": 0.244, "PA": 216, "B": 0.224, "name": "altmg101", "year": 1965}, {"A": 0.28, "PA": 234, "B": 0.271, "name": "altuj001", "year": 2011}, {"A": 0.298, "PA": 630, "B": 0.282, "name": "altuj001", "year": 2012}, {"A": 0.267, "PA": 672, "B": 0.296, "name": "altuj001", "year": 2013}, {"A": 0.352, "PA": 707, "B": 0.329, "name": "altuj001", "year": 2014}, {"A": 0.303, "PA": 689, "B": 0.323, "name": "altuj001", "year": 2015}, {"A": 0.301, "PA": 717, "B": 0.37, "name": "altuj001", "year": 2016}, {"A": 0.378, "PA": 662, "B": 0.316, "name": "altuj001", "year": 2017}, {"A": 0.332, "PA": 599, "B": 0.301, "name": "altuj001", "year": 2018}, {"A": 0.333, "PA": 230, "B": 0.214, "name": "alusg101", "year": 1962}, {"A": 0.294, "PA": 252, "B": 0.243, "name": "alusg101", "year": 1963}, {"A": 0.197, "PA": 238, "B": 0.271, "name": "alusg101", "year": 1964}, {"A": 0.232, "PA": 221, "B": 0.23, "name": "alvag001", "year": 1998}, {"A": 0.218, "PA": 278, "B": 0.213, "name": "alval101", "year": 1971}, {"A": 0.177, "PA": 269, "B": 0.242, "name": "alval101", "year": 1972}, {"A": 0.267, "PA": 386, "B": 0.245, "name": "alvap001", "year": 2010}, {"A": 0.168, "PA": 262, "B": 0.213, "name": "alvap001", "year": 2011}, {"A": 0.241, "PA": 585, "B": 0.246, "name": "alvap001", "year": 2012}, {"A": 0.232, "PA": 614, "B": 0.233, "name": "alvap001", "year": 2013}, {"A": 0.191, "PA": 445, "B": 0.268, "name": "alvap001", "year": 2014}, {"A": 0.206, "PA": 491, "B": 0.276, "name": "alvap001", "year": 2015}, {"A": 0.258, "PA": 377, "B": 0.237, "name": "alvap001", "year": 2016}, {"A": 0.29, "PA": 660, "B": 0.254, "name": "alvim101", "year": 1963}, {"A": 0.23, "PA": 419, "B": 0.276, "name": "alvim101", "year": 1964}, {"A": 0.219, "PA": 670, "B": 0.27, "name": "alvim101", "year": 1965}, {"A": 0.252, "PA": 655, "B": 0.237, "name": "alvim101", "year": 1966}, {"A": 0.253, "PA": 697, "B": 0.258, "name": "alvim101", "year": 1967}, {"A": 0.229, "PA": 503, "B": 0.217, "name": "alvim101", "year": 1968}, {"A": 0.276, "PA": 276, "B": 0.224, "name": "alyeb101", "year": 1969}, {"A": 0.274, "PA": 290, "B": 0.308, "name": "alyeb101", "year": 1970}, {"A": 0.286, "PA": 361, "B": 0.268, "name": "amalj101", "year": 1960}, {"A": 0.259, "PA": 433, "B": 0.251, "name": "amalj101", "year": 1961}, {"A": 0.251, "PA": 435, "B": 0.222, "name": "amalj101", "year": 1962}, {"A": 0.262, "PA": 372, "B": 0.22, "name": "amalj101", "year": 1964}, {"A": 0.234, "PA": 300, "B": 0.244, "name": "amara001", "year": 2012}, {"A": 0.228, "PA": 396, "B": 0.243, "name": "amara001", "year": 2013}, {"A": 0.25, "PA": 466, "B": 0.227, "name": "amara001", "year": 2014}, {"A": 0.206, "PA": 357, "B": 0.201, "name": "amara001", "year": 2015}, {"A": 0.301, "PA": 421, "B": 0.28, "name": "amarr001", "year": 1993}, {"A": 0.273, "PA": 262, "B": 0.254, "name": "amarr001", "year": 1994}, {"A": 0.271, "PA": 261, "B": 0.291, "name": "amarr001", "year": 1995}, {"A": 0.267, "PA": 369, "B": 0.317, "name": "amarr001", "year": 1996}, {"A": 0.304, "PA": 210, "B": 0.265, "name": "amarr001", "year": 1997}, {"A": 0.207, "PA": 427, "B": 0.232, "name": "amarr002", "year": 1992}, {"A": 0.232, "PA": 292, "B": 0.229, "name": "amarr101", "year": 1960}, {"A": 0.284, "PA": 446, "B": 0.231, "name": "amarr101", "year": 1961}, {"A": 0.227, "PA": 265, "B": 0.258, "name": "amarr101", "year": 1962}, {"A": 0.196, "PA": 245, "B": 0.24, "name": "amarr101", "year": 1963}, {"A": 0.238, "PA": 323, "B": 0.29, "name": "amarr101", "year": 1964}, {"A": 0.218, "PA": 218, "B": 0.202, "name": "amarr101", "year": 1965}, {"A": 0.233, "PA": 470, "B": 0.212, "name": "amarr101", "year": 1967}, {"A": 0.242, "PA": 452, "B": 0.217, "name": "amblw101", "year": 1938}, {"A": 0.21, "PA": 263, "B": 0.207, "name": "amblw101", "year": 1939}, {"A": 0.235, "PA": 378, "B": 0.287, "name": "ameza001", "year": 2006}, {"A": 0.247, "PA": 448, "B": 0.277, "name": "ameza001", "year": 2007}, {"A": 0.245, "PA": 337, "B": 0.283, "name": "ameza001", "year": 2008}, {"A": 0.239, "PA": 298, "B": 0.312, "name": "amors101", "year": 1954}, {"A": 0.24, "PA": 455, "B": 0.255, "name": "amors101", "year": 1955}, {"A": 0.292, "PA": 361, "B": 0.234, "name": "amors101", "year": 1956}, {"A": 0.285, "PA": 293, "B": 0.268, "name": "amors101", "year": 1957}, {"A": 0.178, "PA": 241, "B": 0.243, "name": "andea102", "year": 1941}, {"A": 0.265, "PA": 364, "B": 0.161, "name": "andeb001", "year": 1988}, {"A": 0.193, "PA": 317, "B": 0.218, "name": "andeb001", "year": 1989}, {"A": 0.283, "PA": 279, "B": 0.186, "name": "andeb001", "year": 1990}, {"A": 0.236, "PA": 312, "B": 0.226, "name": "andeb001", "year": 1991}, {"A": 0.281, "PA": 749, "B": 0.261, "name": "andeb001", "year": 1992}, {"A": 0.264, "PA": 664, "B": 0.259, "name": "andeb001", "year": 1993}, {"A": 0.265, "PA": 525, "B": 0.259, "name": "andeb001", "year": 1994}, {"A": 0.238, "PA": 657, "B": 0.283, "name": "andeb001", "year": 1995}, {"A": 0.312, "PA": 687, "B": 0.282, "name": "andeb001", "year": 1996}, {"A": 0.308, "PA": 696, "B": 0.267, "name": "andeb001", "year": 1997}, {"A": 0.253, "PA": 574, "B": 0.218, "name": "andeb001", "year": 1998}, {"A": 0.236, "PA": 692, "B": 0.317, "name": "andeb001", "year": 1999}, {"A": 0.277, "PA": 618, "B": 0.24, "name": "andeb001", "year": 2000}, {"A": 0.2, "PA": 501, "B": 0.204, "name": "andeb001", "year": 2001}, {"A": 0.24, "PA": 406, "B": 0.206, "name": "andeb003", "year": 2006}, {"A": 0.2, "PA": 231, "B": 0.284, "name": "andeb003", "year": 2009}, {"A": 0.278, "PA": 670, "B": 0.267, "name": "andeb006", "year": 2018}, {"A": 0.23, "PA": 433, "B": 0.271, "name": "anded001", "year": 1984}, {"A": 0.184, "PA": 262, "B": 0.219, "name": "anded001", "year": 1985}, {"A": 0.217, "PA": 241, "B": 0.269, "name": "anded001", "year": 1986}, {"A": 0.258, "PA": 297, "B": 0.214, "name": "anded001", "year": 1987}, {"A": 0.306, "PA": 325, "B": 0.195, "name": "anded001", "year": 1988}, {"A": 0.283, "PA": 240, "B": 0.205, "name": "anded001", "year": 1991}, {"A": 0.346, "PA": 400, "B": 0.297, "name": "andeg001", "year": 1995}, {"A": 0.226, "PA": 642, "B": 0.336, "name": "andeg001", "year": 1996}, {"A": 0.292, "PA": 662, "B": 0.31, "name": "andeg001", "year": 1997}, {"A": 0.278, "PA": 658, "B": 0.313, "name": "andeg001", "year": 1998}, {"A": 0.31, "PA": 660, "B": 0.295, "name": "andeg001", "year": 1999}, {"A": 0.313, "PA": 681, "B": 0.26, "name": "andeg001", "year": 2000}, {"A": 0.289, "PA": 704, "B": 0.287, "name": "andeg001", "year": 2001}, {"A": 0.311, "PA": 678, "B": 0.299, "name": "andeg001", "year": 2002}, {"A": 0.34, "PA": 673, "B": 0.29, "name": "andeg001", "year": 2003}, {"A": 0.29, "PA": 475, "B": 0.309, "name": "andeg001", "year": 2004}, {"A": 0.288, "PA": 603, "B": 0.278, "name": "andeg001", "year": 2005}, {"A": 0.313, "PA": 588, "B": 0.245, "name": "andeg001", "year": 2006}, {"A": 0.288, "PA": 450, "B": 0.305, "name": "andeg001", "year": 2007}, {"A": 0.289, "PA": 593, "B": 0.295, "name": "andeg001", "year": 2008}, {"A": 0.285, "PA": 534, "B": 0.248, "name": "andeg001", "year": 2009}, {"A": 0.279, "PA": 453, "B": 0.251, "name": "andeh101", "year": 1957}, {"A": 0.311, "PA": 585, "B": 0.291, "name": "andeh101", "year": 1958}, {"A": 0.237, "PA": 561, "B": 0.243, "name": "andeh101", "year": 1959}, {"A": 0.196, "PA": 264, "B": 0.289, "name": "andej001", "year": 1979}, {"A": 0.245, "PA": 355, "B": 0.208, "name": "andej001", "year": 1980}, {"A": 0.256, "PA": 298, "B": 0.228, "name": "andej004", "year": 2009}, {"A": 0.219, "PA": 248, "B": 0.238, "name": "andek001", "year": 1989}, {"A": 0.27, "PA": 484, "B": 0.233, "name": "andem003", "year": 1999}, {"A": 0.322, "PA": 574, "B": 0.266, "name": "andem003", "year": 2001}, {"A": 0.258, "PA": 592, "B": 0.257, "name": "andem003", "year": 2002}, {"A": 0.257, "PA": 535, "B": 0.28, "name": "andem003", "year": 2003}, {"A": 0.274, "PA": 271, "B": 0.194, "name": "andem003", "year": 2004}, {"A": 0.267, "PA": 260, "B": 0.261, "name": "andem003", "year": 2005}, {"A": 0.276, "PA": 312, "B": 0.315, "name": "andem003", "year": 2006}, {"A": 0.241, "PA": 435, "B": 0.26, "name": "andem101", "year": 1974}, {"A": 0.252, "PA": 271, "B": 0.266, "name": "andem101", "year": 1975}, {"A": 0.208, "PA": 527, "B": 0.228, "name": "andes101", "year": 1959}, {"A": 0.275, "PA": 431, "B": 0.29, "name": "andet001", "year": 2016}, {"A": 0.277, "PA": 606, "B": 0.237, "name": "andet001", "year": 2017}, {"A": 0.239, "PA": 606, "B": 0.24, "name": "andet001", "year": 2018}, {"A": 0.217, "PA": 215, "B": 0.226, "name": "andir001", "year": 2009}, {"A": 0.273, "PA": 511, "B": 0.248, "name": "andir001", "year": 2011}, {"A": 0.201, "PA": 431, "B": 0.221, "name": "andir001", "year": 2012}, {"A": 0.264, "PA": 541, "B": 0.269, "name": "andre001", "year": 2009}, {"A": 0.287, "PA": 674, "B": 0.246, "name": "andre001", "year": 2010}, {"A": 0.321, "PA": 665, "B": 0.234, "name": "andre001", "year": 2011}, {"A": 0.266, "PA": 711, "B": 0.302, "name": "andre001", "year": 2012}, {"A": 0.316, "PA": 698, "B": 0.225, "name": "andre001", "year": 2013}, {"A": 0.247, "PA": 685, "B": 0.279, "name": "andre001", "year": 2014}, {"A": 0.246, "PA": 661, "B": 0.269, "name": "andre001", "year": 2015}, {"A": 0.322, "PA": 568, "B": 0.281, "name": "andre001", "year": 2016}, {"A": 0.323, "PA": 689, "B": 0.271, "name": "andre001", "year": 2017}, {"A": 0.269, "PA": 428, "B": 0.242, "name": "andre001", "year": 2018}, {"A": 0.27, "PA": 578, "B": 0.257, "name": "andrm101", "year": 1967}, {"A": 0.294, "PA": 634, "B": 0.249, "name": "andrm101", "year": 1968}, {"A": 0.261, "PA": 554, "B": 0.321, "name": "andrm101", "year": 1969}, {"A": 0.258, "PA": 681, "B": 0.247, "name": "andrm101", "year": 1970}, {"A": 0.305, "PA": 408, "B": 0.256, "name": "andrm101", "year": 1971}, {"A": 0.208, "PA": 602, "B": 0.232, "name": "andrm101", "year": 1972}, {"A": 0.24, "PA": 321, "B": 0.236, "name": "andrr101", "year": 1975}, {"A": 0.273, "PA": 449, "B": 0.234, "name": "andrr101", "year": 1976}, {"A": 0.247, "PA": 501, "B": 0.278, "name": "andrr101", "year": 1977}, {"A": 0.198, "PA": 241, "B": 0.226, "name": "andrs001", "year": 1995}, {"A": 0.238, "PA": 414, "B": 0.216, "name": "andrs001", "year": 1996}, {"A": 0.216, "PA": 559, "B": 0.259, "name": "andrs001", "year": 1998}, {"A": 0.185, "PA": 404, "B": 0.204, "name": "andrs001", "year": 1999}, {"A": 0.257, "PA": 223, "B": 0.195, "name": "andrs001", "year": 2000}, {"A": 0.262, "PA": 606, "B": 0.332, "name": "andum001", "year": 2018}, {"A": 0.253, "PA": 463, "B": 0.274, "name": "ankir001", "year": 2008}, {"A": 0.223, "PA": 403, "B": 0.241, "name": "ankir001", "year": 2009}, {"A": 0.233, "PA": 240, "B": 0.231, "name": "ankir001", "year": 2010}, {"A": 0.237, "PA": 415, "B": 0.241, "name": "ankir001", "year": 2011}, {"A": 0.196, "PA": 276, "B": 0.188, "name": "anthe001", "year": 1990}, {"A": 0.255, "PA": 483, "B": 0.222, "name": "anthe001", "year": 1992}, {"A": 0.242, "PA": 539, "B": 0.256, "name": "anthe001", "year": 1993}, {"A": 0.223, "PA": 288, "B": 0.25, "name": "anthe001", "year": 1994}, {"A": 0.244, "PA": 218, "B": 0.241, "name": "anthe001", "year": 1996}, {"A": 0.271, "PA": 541, "B": 0.237, "name": "antoj101", "year": 1945}, {"A": 0.321, "PA": 588, "B": 0.258, "name": "aokin001", "year": 2012}, {"A": 0.27, "PA": 674, "B": 0.302, "name": "aokin001", "year": 2013}, {"A": 0.239, "PA": 549, "B": 0.322, "name": "aokin001", "year": 2014}, {"A": 0.303, "PA": 392, "B": 0.274, "name": "aokin001", "year": 2015}, {"A": 0.292, "PA": 467, "B": 0.273, "name": "aokin001", "year": 2016}, {"A": 0.251, "PA": 374, "B": 0.3, "name": "aokin001", "year": 2017}, {"A": 0.28, "PA": 583, "B": 0.253, "name": "aparl101", "year": 1956}, {"A": 0.29, "PA": 640, "B": 0.223, "name": "aparl101", "year": 1957}, {"A": 0.273, "PA": 604, "B": 0.256, "name": "aparl101", "year": 1958}, {"A": 0.267, "PA": 686, "B": 0.242, "name": "aparl101", "year": 1959}, {"A": 0.284, "PA": 669, "B": 0.269, "name": "aparl101", "year": 1960}, {"A": 0.26, "PA": 671, "B": 0.284, "name": "aparl101", "year": 1961}, {"A": 0.251, "PA": 622, "B": 0.23, "name": "aparl101", "year": 1962}, {"A": 0.235, "PA": 652, "B": 0.263, "name": "aparl101", "year": 1963}, {"A": 0.271, "PA": 641, "B": 0.26, "name": "aparl101", "year": 1964}, {"A": 0.248, "PA": 629, "B": 0.2, "name": "aparl101", "year": 1965}, {"A": 0.282, "PA": 707, "B": 0.267, "name": "aparl101", "year": 1966}, {"A": 0.265, "PA": 587, "B": 0.2, "name": "aparl101", "year": 1967}, {"A": 0.239, "PA": 664, "B": 0.289, "name": "aparl101", "year": 1968}, {"A": 0.29, "PA": 681, "B": 0.269, "name": "aparl101", "year": 1969}, {"A": 0.267, "PA": 616, "B": 0.358, "name": "aparl101", "year": 1970}, {"A": 0.227, "PA": 541, "B": 0.236, "name": "aparl101", "year": 1971}, {"A": 0.223, "PA": 474, "B": 0.286, "name": "aparl101", "year": 1972}, {"A": 0.282, "PA": 561, "B": 0.257, "name": "aparl101", "year": 1973}, {"A": 0.263, "PA": 331, "B": 0.194, "name": "appll101", "year": 1931}, {"A": 0.279, "PA": 532, "B": 0.266, "name": "appll101", "year": 1932}, {"A": 0.317, "PA": 671, "B": 0.326, "name": "appll101", "year": 1933}, {"A": 0.3, "PA": 516, "B": 0.307, "name": "appll101", "year": 1934}, {"A": 0.307, "PA": 656, "B": 0.306, "name": "appll101", "year": 1935}, {"A": 0.395, "PA": 618, "B": 0.379, "name": "appll101", "year": 1936}, {"A": 0.275, "PA": 665, "B": 0.352, "name": "appll101", "year": 1937}, {"A": 0.298, "PA": 339, "B": 0.304, "name": "appll101", "year": 1938}, {"A": 0.316, "PA": 633, "B": 0.308, "name": "appll101", "year": 1939}, {"A": 0.351, "PA": 641, "B": 0.342, "name": "appll101", "year": 1940}, {"A": 0.325, "PA": 678, "B": 0.303, "name": "appll101", "year": 1941}, {"A": 0.295, "PA": 613, "B": 0.221, "name": "appll101", "year": 1942}, {"A": 0.315, "PA": 677, "B": 0.339, "name": "appll101", "year": 1943}, {"A": 0.271, "PA": 659, "B": 0.342, "name": "appll101", "year": 1946}, {"A": 0.324, "PA": 573, "B": 0.289, "name": "appll101", "year": 1947}, {"A": 0.306, "PA": 594, "B": 0.32, "name": "appll101", "year": 1948}, {"A": 0.257, "PA": 619, "B": 0.345, "name": "appll101", "year": 1949}, {"A": 0.257, "PA": 443, "B": 0.295, "name": "archg101", "year": 1941}, {"A": 0.359, "PA": 343, "B": 0.281, "name": "archm101", "year": 1924}, {"A": 0.218, "PA": 320, "B": 0.213, "name": "arcij101", "year": 1969}, {"A": 0.2, "PA": 252, "B": 0.243, "name": "arcij101", "year": 1970}, {"A": 0.292, "PA": 378, "B": 0.211, "name": "arcio001", "year": 2013}, {"A": 0.195, "PA": 410, "B": 0.262, "name": "arcio001", "year": 2014}, {"A": 0.255, "PA": 222, "B": 0.157, "name": "arcio001", "year": 2016}, {"A": 0.207, "PA": 216, "B": 0.231, "name": "arcio002", "year": 2016}, {"A": 0.308, "PA": 548, "B": 0.25, "name": "arcio002", "year": 2017}, {"A": 0.255, "PA": 366, "B": 0.213, "name": "arcio002", "year": 2018}, {"A": 0.226, "PA": 248, "B": 0.23, "name": "ardod001", "year": 2005}, {"A": 0.2, "PA": 485, "B": 0.236, "name": "arenj001", "year": 2011}, {"A": 0.28, "PA": 372, "B": 0.187, "name": "arenj001", "year": 2012}, {"A": 0.227, "PA": 497, "B": 0.16, "name": "arenj001", "year": 2013}, {"A": 0.171, "PA": 222, "B": 0.184, "name": "arenj001", "year": 2014}, {"A": 0.235, "PA": 514, "B": 0.298, "name": "arenn001", "year": 2013}, {"A": 0.264, "PA": 467, "B": 0.305, "name": "arenn001", "year": 2014}, {"A": 0.277, "PA": 665, "B": 0.296, "name": "arenn001", "year": 2015}, {"A": 0.294, "PA": 696, "B": 0.294, "name": "arenn001", "year": 2016}, {"A": 0.304, "PA": 680, "B": 0.312, "name": "arenn001", "year": 2017}, {"A": 0.302, "PA": 673, "B": 0.29, "name": "arenn001", "year": 2018}, {"A": 0.216, "PA": 296, "B": 0.255, "name": "arfth101", "year": 1948}, {"A": 0.268, "PA": 332, "B": 0.267, "name": "arfth101", "year": 1950}, {"A": 0.262, "PA": 390, "B": 0.259, "name": "arfth101", "year": 1951}, {"A": 0.243, "PA": 282, "B": 0.296, "name": "ariaa001", "year": 1993}, {"A": 0.243, "PA": 246, "B": 0.292, "name": "ariaa001", "year": 1995}, {"A": 0.316, "PA": 246, "B": 0.243, "name": "ariaa001", "year": 1996}, {"A": 0.296, "PA": 390, "B": 0.307, "name": "ariaa001", "year": 1999}, {"A": 0.23, "PA": 274, "B": 0.246, "name": "ariag001", "year": 1996}, {"A": 0.255, "PA": 344, "B": 0.282, "name": "ariaj001", "year": 2012}, {"A": 0.216, "PA": 236, "B": 0.324, "name": "ariaj001", "year": 2013}, {"A": 0.355, "PA": 469, "B": 0.27, "name": "arleb101", "year": 1931}, {"A": 0.271, "PA": 392, "B": 0.213, "name": "armat001", "year": 1977}, {"A": 0.209, "PA": 258, "B": 0.217, "name": "armat001", "year": 1978}, {"A": 0.304, "PA": 297, "B": 0.189, "name": "armat001", "year": 1979}, {"A": 0.274, "PA": 666, "B": 0.282, "name": "armat001", "year": 1980}, {"A": 0.252, "PA": 462, "B": 0.269, "name": "armat001", "year": 1981}, {"A": 0.255, "PA": 578, "B": 0.212, "name": "armat001", "year": 1982}, {"A": 0.247, "PA": 613, "B": 0.19, "name": "armat001", "year": 1983}, {"A": 0.242, "PA": 679, "B": 0.292, "name": "armat001", "year": 1984}, {"A": 0.224, "PA": 410, "B": 0.303, "name": "armat001", "year": 1985}, {"A": 0.314, "PA": 453, "B": 0.213, "name": "armat001", "year": 1986}, {"A": 0.244, "PA": 393, "B": 0.302, "name": "armat001", "year": 1988}, {"A": 0.194, "PA": 211, "B": 0.323, "name": "armat001", "year": 1989}, {"A": 0.301, "PA": 449, "B": 0.285, "name": "arnom101", "year": 1937}, {"A": 0.235, "PA": 551, "B": 0.315, "name": "arnom101", "year": 1938}, {"A": 0.305, "PA": 561, "B": 0.338, "name": "arnom101", "year": 1939}, {"A": 0.247, "PA": 383, "B": 0.253, "name": "arnom101", "year": 1940}, {"A": 0.287, "PA": 232, "B": 0.27, "name": "arnom101", "year": 1941}, {"A": 0.236, "PA": 434, "B": 0.267, "name": "aschc001", "year": 2014}, {"A": 0.271, "PA": 456, "B": 0.215, "name": "aschc001", "year": 2015}, {"A": 0.15, "PA": 218, "B": 0.269, "name": "aschc001", "year": 2016}, {"A": 0.268, "PA": 302, "B": 0.19, "name": "ashba001", "year": 1975}, {"A": 0.25, "PA": 283, "B": 0.225, "name": "ashba001", "year": 1976}, {"A": 0.185, "PA": 459, "B": 0.229, "name": "ashba001", "year": 1977}, {"A": 0.309, "PA": 298, "B": 0.223, "name": "ashba001", "year": 1978}, {"A": 0.212, "PA": 370, "B": 0.192, "name": "ashba001", "year": 1979}, {"A": 0.263, "PA": 394, "B": 0.248, "name": "ashba001", "year": 1980}, {"A": 0.274, "PA": 296, "B": 0.267, "name": "ashba001", "year": 1981}, {"A": 0.258, "PA": 372, "B": 0.254, "name": "ashba001", "year": 1982}, {"A": 0.238, "PA": 311, "B": 0.221, "name": "ashba001", "year": 1983}, {"A": 0.238, "PA": 361, "B": 0.275, "name": "ashba001", "year": 1986}, {"A": 0.312, "PA": 447, "B": 0.263, "name": "ashba001", "year": 1987}, {"A": 0.286, "PA": 261, "B": 0.187, "name": "ashba001", "year": 1988}, {"A": 0.375, "PA": 530, "B": 0.301, "name": "ashbr101", "year": 1948}, {"A": 0.271, "PA": 724, "B": 0.3, "name": "ashbr101", "year": 1949}, {"A": 0.318, "PA": 670, "B": 0.286, "name": "ashbr101", "year": 1950}, {"A": 0.376, "PA": 712, "B": 0.313, "name": "ashbr101", "year": 1951}, {"A": 0.267, "PA": 702, "B": 0.296, "name": "ashbr101", "year": 1952}, {"A": 0.346, "PA": 703, "B": 0.311, "name": "ashbr101", "year": 1953}, {"A": 0.29, "PA": 703, "B": 0.333, "name": "ashbr101", "year": 1954}, {"A": 0.342, "PA": 644, "B": 0.332, "name": "ashbr101", "year": 1955}, {"A": 0.318, "PA": 718, "B": 0.287, "name": "ashbr101", "year": 1956}, {"A": 0.308, "PA": 729, "B": 0.283, "name": "ashbr101", "year": 1957}, {"A": 0.376, "PA": 724, "B": 0.325, "name": "ashbr101", "year": 1958}, {"A": 0.244, "PA": 659, "B": 0.289, "name": "ashbr101", "year": 1959}, {"A": 0.295, "PA": 671, "B": 0.287, "name": "ashbr101", "year": 1960}, {"A": 0.252, "PA": 367, "B": 0.264, "name": "ashbr101", "year": 1961}, {"A": 0.297, "PA": 473, "B": 0.313, "name": "ashbr101", "year": 1962}, {"A": 0.245, "PA": 277, "B": 0.188, "name": "ashft001", "year": 1977}, {"A": 0.26, "PA": 244, "B": 0.218, "name": "ashlb001", "year": 1995}, {"A": 0.272, "PA": 595, "B": 0.26, "name": "asprb101", "year": 1962}, {"A": 0.199, "PA": 514, "B": 0.227, "name": "asprb101", "year": 1963}, {"A": 0.262, "PA": 608, "B": 0.295, "name": "asprb101", "year": 1964}, {"A": 0.271, "PA": 628, "B": 0.255, "name": "asprb101", "year": 1965}, {"A": 0.276, "PA": 603, "B": 0.226, "name": "asprb101", "year": 1966}, {"A": 0.284, "PA": 538, "B": 0.307, "name": "asprb101", "year": 1967}, {"A": 0.206, "PA": 457, "B": 0.241, "name": "asprb101", "year": 1968}, {"A": 0.203, "PA": 377, "B": 0.243, "name": "asprb101", "year": 1971}, {"A": 0.207, "PA": 300, "B": 0.233, "name": "asprk101", "year": 1958}, {"A": 0.229, "PA": 255, "B": 0.258, "name": "asprk101", "year": 1959}, {"A": 0.279, "PA": 523, "B": 0.296, "name": "asprk101", "year": 1960}, {"A": 0.187, "PA": 354, "B": 0.263, "name": "asprk101", "year": 1961}, {"A": 0.324, "PA": 235, "B": 0.245, "name": "asseb101", "year": 1980}, {"A": 0.265, "PA": 370, "B": 0.233, "name": "astrj101", "year": 1952}, {"A": 0.283, "PA": 289, "B": 0.308, "name": "astrj101", "year": 1953}, {"A": 0.254, "PA": 252, "B": 0.192, "name": "astrj101", "year": 1954}, {"A": 0.253, "PA": 338, "B": 0.25, "name": "astrj101", "year": 1955}, {"A": 0.265, "PA": 343, "B": 0.274, "name": "asuac001", "year": 2017}, {"A": 0.202, "PA": 218, "B": 0.19, "name": "asuac001", "year": 2018}, {"A": 0.312, "PA": 573, "B": 0.26, "name": "atkig001", "year": 2005}, {"A": 0.305, "PA": 695, "B": 0.35, "name": "atkig001", "year": 2006}, {"A": 0.293, "PA": 684, "B": 0.308, "name": "atkig001", "year": 2007}, {"A": 0.296, "PA": 664, "B": 0.277, "name": "atkig001", "year": 2008}, {"A": 0.22, "PA": 398, "B": 0.232, "name": "atkig001", "year": 2009}, {"A": 0.304, "PA": 406, "B": 0.274, "name": "atwet101", "year": 1952}, {"A": 0.256, "PA": 251, "B": 0.22, "name": "atwet101", "year": 1953}, {"A": 0.318, "PA": 340, "B": 0.264, "name": "atwet101", "year": 1954}, {"A": 0.203, "PA": 253, "B": 0.223, "name": "atwet101", "year": 1955}, {"A": 0.241, "PA": 313, "B": 0.245, "name": "atwob101", "year": 1937}, {"A": 0.234, "PA": 311, "B": 0.153, "name": "atwob101", "year": 1938}, {"A": 0.203, "PA": 229, "B": 0.177, "name": "atwob101", "year": 1940}, {"A": 0.219, "PA": 263, "B": 0.185, "name": "auerr101", "year": 1971}, {"A": 0.196, "PA": 605, "B": 0.239, "name": "auerr101", "year": 1972}, {"A": 0.224, "PA": 494, "B": 0.259, "name": "aultd101", "year": 1977}, {"A": 0.232, "PA": 352, "B": 0.245, "name": "aurir001", "year": 1996}, {"A": 0.269, "PA": 453, "B": 0.262, "name": "aurir001", "year": 1998}, {"A": 0.294, "PA": 614, "B": 0.268, "name": "aurir001", "year": 1999}, {"A": 0.233, "PA": 571, "B": 0.307, "name": "aurir001", "year": 2000}, {"A": 0.365, "PA": 689, "B": 0.281, "name": "aurir001", "year": 2001}, {"A": 0.25, "PA": 589, "B": 0.261, "name": "aurir001", "year": 2002}, {"A": 0.326, "PA": 545, "B": 0.228, "name": "aurir001", "year": 2003}, {"A": 0.247, "PA": 450, "B": 0.244, "name": "aurir001", "year": 2004}, {"A": 0.29, "PA": 468, "B": 0.271, "name": "aurir001", "year": 2005}, {"A": 0.282, "PA": 481, "B": 0.314, "name": "aurir001", "year": 2006}, {"A": 0.261, "PA": 358, "B": 0.242, "name": "aurir001", "year": 2007}, {"A": 0.287, "PA": 440, "B": 0.278, "name": "aurir001", "year": 2008}, {"A": 0.28, "PA": 366, "B": 0.223, "name": "ausmb001", "year": 1994}, {"A": 0.25, "PA": 369, "B": 0.339, "name": "ausmb001", "year": 1995}, {"A": 0.214, "PA": 425, "B": 0.23, "name": "ausmb001", "year": 1996}, {"A": 0.244, "PA": 478, "B": 0.287, "name": "ausmb001", "year": 1997}, {"A": 0.209, "PA": 471, "B": 0.333, "name": "ausmb001", "year": 1998}, {"A": 0.239, "PA": 527, "B": 0.306, "name": "ausmb001", "year": 1999}, {"A": 0.249, "PA": 604, "B": 0.28, "name": "ausmb001", "year": 2000}, {"A": 0.215, "PA": 461, "B": 0.248, "name": "ausmb001", "year": 2001}, {"A": 0.245, "PA": 496, "B": 0.268, "name": "ausmb001", "year": 2002}, {"A": 0.236, "PA": 509, "B": 0.221, "name": "ausmb001", "year": 2003}, {"A": 0.25, "PA": 449, "B": 0.245, "name": "ausmb001", "year": 2004}, {"A": 0.27, "PA": 450, "B": 0.246, "name": "ausmb001", "year": 2005}, {"A": 0.242, "PA": 502, "B": 0.217, "name": "ausmb001", "year": 2006}, {"A": 0.238, "PA": 397, "B": 0.23, "name": "ausmb001", "year": 2007}, {"A": 0.212, "PA": 250, "B": 0.221, "name": "ausmb001", "year": 2008}, {"A": 0.217, "PA": 330, "B": 0.33, "name": "austj101", "year": 1920}, {"A": 0.211, "PA": 269, "B": 0.244, "name": "austt001", "year": 2018}, {"A": 0.282, "PA": 440, "B": 0.295, "name": "avenb001", "year": 1999}, {"A": 0.341, "PA": 680, "B": 0.322, "name": "avere101", "year": 1929}, {"A": 0.353, "PA": 606, "B": 0.326, "name": "avere101", "year": 1930}, {"A": 0.324, "PA": 701, "B": 0.343, "name": "avere101", "year": 1931}, {"A": 0.305, "PA": 712, "B": 0.322, "name": "avere101", "year": 1932}, {"A": 0.302, "PA": 658, "B": 0.297, "name": "avere101", "year": 1933}, {"A": 0.31, "PA": 705, "B": 0.314, "name": "avere101", "year": 1934}, {"A": 0.325, "PA": 638, "B": 0.252, "name": "avere101", "year": 1935}, {"A": 0.374, "PA": 682, "B": 0.38, "name": "avere101", "year": 1936}, {"A": 0.272, "PA": 701, "B": 0.324, "name": "avere101", "year": 1937}, {"A": 0.342, "PA": 567, "B": 0.318, "name": "avere101", "year": 1938}, {"A": 0.242, "PA": 427, "B": 0.287, "name": "avere101", "year": 1939}, {"A": 0.28, "PA": 390, "B": 0.254, "name": "avere102", "year": 1961}, {"A": 0.22, "PA": 233, "B": 0.218, "name": "avere102", "year": 1962}, {"A": 0.18, "PA": 333, "B": 0.267, "name": "avila001", "year": 2010}, {"A": 0.285, "PA": 551, "B": 0.303, "name": "avila001", "year": 2011}, {"A": 0.236, "PA": 434, "B": 0.247, "name": "avila001", "year": 2012}, {"A": 0.221, "PA": 379, "B": 0.235, "name": "avila001", "year": 2013}, {"A": 0.219, "PA": 457, "B": 0.216, "name": "avila001", "year": 2014}, {"A": 0.295, "PA": 376, "B": 0.23, "name": "avila001", "year": 2017}, {"A": 0.174, "PA": 234, "B": 0.152, "name": "avila001", "year": 2018}, {"A": 0.343, "PA": 238, "B": 0.257, "name": "avilb101", "year": 1950}, {"A": 0.296, "PA": 615, "B": 0.312, "name": "avilb101", "year": 1951}, {"A": 0.277, "PA": 684, "B": 0.32, "name": "avilb101", "year": 1952}, {"A": 0.308, "PA": 634, "B": 0.264, "name": "avilb101", "year": 1953}, {"A": 0.336, "PA": 638, "B": 0.341, "name": "avilb101", "year": 1954}, {"A": 0.269, "PA": 643, "B": 0.273, "name": "avilb101", "year": 1955}, {"A": 0.226, "PA": 598, "B": 0.221, "name": "avilb101", "year": 1956}, {"A": 0.272, "PA": 528, "B": 0.264, "name": "avilb101", "year": 1957}, {"A": 0.27, "PA": 445, "B": 0.233, "name": "avilb101", "year": 1958}, {"A": 0.238, "PA": 306, "B": 0.215, "name": "avilb101", "year": 1959}, {"A": 0.352, "PA": 441, "B": 0.296, "name": "avilm001", "year": 2008}, {"A": 0.316, "PA": 448, "B": 0.294, "name": "avilm001", "year": 2010}, {"A": 0.239, "PA": 309, "B": 0.276, "name": "avilm001", "year": 2011}, {"A": 0.29, "PA": 546, "B": 0.215, "name": "avilm001", "year": 2012}, {"A": 0.257, "PA": 394, "B": 0.247, "name": "avilm001", "year": 2013}, {"A": 0.259, "PA": 374, "B": 0.235, "name": "avilm001", "year": 2014}, {"A": 0.257, "PA": 317, "B": 0.195, "name": "avilm001", "year": 2015}, {"A": 0.24, "PA": 376, "B": 0.315, "name": "aybae001", "year": 2008}, {"A": 0.306, "PA": 556, "B": 0.315, "name": "aybae001", "year": 2009}, {"A": 0.257, "PA": 589, "B": 0.248, "name": "aybae001", "year": 2010}, {"A": 0.278, "PA": 605, "B": 0.278, "name": "aybae001", "year": 2011}, {"A": 0.303, "PA": 554, "B": 0.275, "name": "aybae001", "year": 2012}, {"A": 0.276, "PA": 589, "B": 0.265, "name": "aybae001", "year": 2013}, {"A": 0.27, "PA": 642, "B": 0.285, "name": "aybae001", "year": 2014}, {"A": 0.271, "PA": 638, "B": 0.268, "name": "aybae001", "year": 2015}, {"A": 0.222, "PA": 459, "B": 0.266, "name": "aybae001", "year": 2016}, {"A": 0.238, "PA": 370, "B": 0.229, "name": "aybae001", "year": 2017}, {"A": 0.327, "PA": 278, "B": 0.236, "name": "aybaw001", "year": 2006}, {"A": 0.242, "PA": 361, "B": 0.265, "name": "aybaw001", "year": 2008}, {"A": 0.238, "PA": 336, "B": 0.268, "name": "aybaw001", "year": 2009}, {"A": 0.239, "PA": 309, "B": 0.218, "name": "aybaw001", "year": 2010}, {"A": 0.232, "PA": 248, "B": 0.225, "name": "azcuj101", "year": 1962}, {"A": 0.303, "PA": 343, "B": 0.257, "name": "azcuj101", "year": 1963}, {"A": 0.292, "PA": 294, "B": 0.255, "name": "azcuj101", "year": 1964}, {"A": 0.248, "PA": 371, "B": 0.214, "name": "azcuj101", "year": 1965}, {"A": 0.246, "PA": 330, "B": 0.301, "name": "azcuj101", "year": 1966}, {"A": 0.314, "PA": 324, "B": 0.19, "name": "azcuj101", "year": 1967}, {"A": 0.248, "PA": 389, "B": 0.317, "name": "azcuj101", "year": 1968}, {"A": 0.168, "PA": 365, "B": 0.268, "name": "azcuj101", "year": 1969}, {"A": 0.265, "PA": 381, "B": 0.218, "name": "azcuj101", "year": 1970}, {"A": 0.24, "PA": 401, "B": 0.222, "name": "babel101", "year": 1953}, {"A": 0.298, "PA": 313, "B": 0.246, "name": "backw001", "year": 1982}, {"A": 0.311, "PA": 499, "B": 0.247, "name": "backw001", "year": 1984}, {"A": 0.264, "PA": 574, "B": 0.281, "name": "backw001", "year": 1985}, {"A": 0.275, "PA": 440, "B": 0.372, "name": "backw001", "year": 1986}, {"A": 0.216, "PA": 335, "B": 0.289, "name": "backw001", "year": 1987}, {"A": 0.308, "PA": 347, "B": 0.297, "name": "backw001", "year": 1988}, {"A": 0.246, "PA": 337, "B": 0.21, "name": "backw001", "year": 1989}, {"A": 0.31, "PA": 361, "B": 0.273, "name": "backw001", "year": 1990}, {"A": 0.268, "PA": 427, "B": 0.258, "name": "badeh001", "year": 2018}, {"A": 0.176, "PA": 254, "B": 0.304, "name": "badgr101", "year": 1930}, {"A": 0.309, "PA": 338, "B": 0.198, "name": "baerc001", "year": 1990}, {"A": 0.313, "PA": 653, "B": 0.264, "name": "baerc001", "year": 1991}, {"A": 0.29, "PA": 716, "B": 0.335, "name": "baerc001", "year": 1992}, {"A": 0.309, "PA": 679, "B": 0.331, "name": "baerc001", "year": 1993}, {"A": 0.333, "PA": 468, "B": 0.296, "name": "baerc001", "year": 1994}, {"A": 0.306, "PA": 600, "B": 0.323, "name": "baerc001", "year": 1995}, {"A": 0.22, "PA": 544, "B": 0.286, "name": "baerc001", "year": 1996}, {"A": 0.292, "PA": 498, "B": 0.269, "name": "baerc001", "year": 1997}, {"A": 0.25, "PA": 551, "B": 0.281, "name": "baerc001", "year": 1998}, {"A": 0.36, "PA": 231, "B": 0.327, "name": "baerc001", "year": 2003}, {"A": 0.151, "PA": 229, "B": 0.188, "name": "baezj001", "year": 2014}, {"A": 0.267, "PA": 450, "B": 0.278, "name": "baezj001", "year": 2016}, {"A": 0.276, "PA": 508, "B": 0.266, "name": "baezj001", "year": 2017}, {"A": 0.279, "PA": 645, "B": 0.301, "name": "baezj001", "year": 2018}, {"A": 0.26, "PA": 333, "B": 0.256, "name": "baezj101", "year": 1977}, {"A": 0.267, "PA": 649, "B": 0.325, "name": "bagwj001", "year": 1991}, {"A": 0.283, "PA": 697, "B": 0.262, "name": "bagwj001", "year": 1992}, {"A": 0.34, "PA": 608, "B": 0.303, "name": "bagwj001", "year": 1993}, {"A": 0.4, "PA": 479, "B": 0.333, "name": "bagwj001", "year": 1994}, {"A": 0.252, "PA": 539, "B": 0.327, "name": "bagwj001", "year": 1995}, {"A": 0.287, "PA": 718, "B": 0.348, "name": "bagwj001", "year": 1996}, {"A": 0.276, "PA": 717, "B": 0.294, "name": "bagwj001", "year": 1997}, {"A": 0.304, "PA": 661, "B": 0.303, "name": "bagwj001", "year": 1998}, {"A": 0.275, "PA": 729, "B": 0.331, "name": "bagwj001", "year": 1999}, {"A": 0.284, "PA": 719, "B": 0.338, "name": "bagwj001", "year": 2000}, {"A": 0.282, "PA": 717, "B": 0.294, "name": "bagwj001", "year": 2001}, {"A": 0.291, "PA": 691, "B": 0.29, "name": "bagwj001", "year": 2002}, {"A": 0.278, "PA": 702, "B": 0.277, "name": "bagwj001", "year": 2003}, {"A": 0.278, "PA": 678, "B": 0.254, "name": "bagwj001", "year": 2004}, {"A": 0.262, "PA": 523, "B": 0.349, "name": "bailb001", "year": 1977}, {"A": 0.273, "PA": 676, "B": 0.254, "name": "bailb001", "year": 1978}, {"A": 0.185, "PA": 465, "B": 0.268, "name": "bailb001", "year": 1979}, {"A": 0.205, "PA": 388, "B": 0.267, "name": "bailb001", "year": 1980}, {"A": 0.299, "PA": 404, "B": 0.25, "name": "bailb001", "year": 1982}, {"A": 0.28, "PA": 368, "B": 0.218, "name": "bailb001", "year": 1983}, {"A": 0.219, "PA": 640, "B": 0.236, "name": "bailb103", "year": 1963}, {"A": 0.273, "PA": 582, "B": 0.289, "name": "bailb103", "year": 1964}, {"A": 0.266, "PA": 702, "B": 0.245, "name": "bailb103", "year": 1965}, {"A": 0.25, "PA": 433, "B": 0.306, "name": "bailb103", "year": 1966}, {"A": 0.213, "PA": 372, "B": 0.241, "name": "bailb103", "year": 1967}, {"A": 0.222, "PA": 365, "B": 0.23, "name": "bailb103", "year": 1968}, {"A": 0.284, "PA": 405, "B": 0.248, "name": "bailb103", "year": 1969}, {"A": 0.254, "PA": 429, "B": 0.321, "name": "bailb103", "year": 1970}, {"A": 0.234, "PA": 654, "B": 0.268, "name": "bailb103", "year": 1971}, {"A": 0.235, "PA": 559, "B": 0.231, "name": "bailb103", "year": 1972}, {"A": 0.28, "PA": 607, "B": 0.265, "name": "bailb103", "year": 1973}, {"A": 0.278, "PA": 614, "B": 0.281, "name": "bailb103", "year": 1974}, {"A": 0.284, "PA": 279, "B": 0.264, "name": "bailb103", "year": 1975}, {"A": 0.216, "PA": 223, "B": 0.18, "name": "baile101", "year": 1954}, {"A": 0.322, "PA": 448, "B": 0.28, "name": "baile101", "year": 1956}, {"A": 0.262, "PA": 472, "B": 0.258, "name": "baile101", "year": 1957}, {"A": 0.291, "PA": 414, "B": 0.22, "name": "baile101", "year": 1958}, {"A": 0.257, "PA": 447, "B": 0.27, "name": "baile101", "year": 1959}, {"A": 0.277, "PA": 511, "B": 0.244, "name": "baile101", "year": 1960}, {"A": 0.202, "PA": 438, "B": 0.293, "name": "baile101", "year": 1961}, {"A": 0.24, "PA": 305, "B": 0.223, "name": "baile101", "year": 1962}, {"A": 0.272, "PA": 361, "B": 0.254, "name": "baile101", "year": 1963}, {"A": 0.24, "PA": 309, "B": 0.28, "name": "baile101", "year": 1964}, {"A": 0.224, "PA": 471, "B": 0.3, "name": "bailg101", "year": 1923}, {"A": 0.203, "PA": 403, "B": 0.22, "name": "bailm001", "year": 1984}, {"A": 0.302, "PA": 402, "B": 0.234, "name": "bailm001", "year": 1985}, {"A": 0.254, "PA": 518, "B": 0.254, "name": "bainh001", "year": 1980}, {"A": 0.31, "PA": 296, "B": 0.268, "name": "bainh001", "year": 1981}, {"A": 0.249, "PA": 668, "B": 0.29, "name": "bainh001", "year": 1982}, {"A": 0.265, "PA": 655, "B": 0.292, "name": "bainh001", "year": 1983}, {"A": 0.312, "PA": 629, "B": 0.295, "name": "bainh001", "year": 1984}, {"A": 0.302, "PA": 693, "B": 0.316, "name": "bainh001", "year": 1985}, {"A": 0.339, "PA": 618, "B": 0.256, "name": "bainh001", "year": 1986}, {"A": 0.266, "PA": 554, "B": 0.32, "name": "bainh001", "year": 1987}, {"A": 0.288, "PA": 674, "B": 0.266, "name": "bainh001", "year": 1988}, {"A": 0.334, "PA": 583, "B": 0.286, "name": "bainh001", "year": 1989}, {"A": 0.339, "PA": 489, "B": 0.225, "name": "bainh001", "year": 1990}, {"A": 0.283, "PA": 566, "B": 0.306, "name": "bainh001", "year": 1991}, {"A": 0.25, "PA": 542, "B": 0.257, "name": "bainh001", "year": 1992}, {"A": 0.315, "PA": 480, "B": 0.309, "name": "bainh001", "year": 1993}, {"A": 0.311, "PA": 357, "B": 0.28, "name": "bainh001", "year": 1994}, {"A": 0.284, "PA": 459, "B": 0.311, "name": "bainh001", "year": 1995}, {"A": 0.336, "PA": 572, "B": 0.287, "name": "bainh001", "year": 1996}, {"A": 0.324, "PA": 509, "B": 0.278, "name": "bainh001", "year": 1997}, {"A": 0.302, "PA": 328, "B": 0.298, "name": "bainh001", "year": 1998}, {"A": 0.322, "PA": 486, "B": 0.301, "name": "bainh001", "year": 1999}, {"A": 0.255, "PA": 320, "B": 0.253, "name": "bainh001", "year": 2000}, {"A": 0.322, "PA": 503, "B": 0.318, "name": "baked002", "year": 1972}, {"A": 0.275, "PA": 686, "B": 0.301, "name": "baked002", "year": 1973}, {"A": 0.261, "PA": 656, "B": 0.25, "name": "baked002", "year": 1974}, {"A": 0.221, "PA": 567, "B": 0.297, "name": "baked002", "year": 1975}, {"A": 0.271, "PA": 421, "B": 0.217, "name": "baked002", "year": 1976}, {"A": 0.283, "PA": 604, "B": 0.298, "name": "baked002", "year": 1977}, {"A": 0.276, "PA": 579, "B": 0.246, "name": "baked002", "year": 1978}, {"A": 0.257, "PA": 616, "B": 0.29, "name": "baked002", "year": 1979}, {"A": 0.313, "PA": 638, "B": 0.273, "name": "baked002", "year": 1980}, {"A": 0.325, "PA": 438, "B": 0.315, "name": "baked002", "year": 1981}, {"A": 0.325, "PA": 640, "B": 0.276, "name": "baked002", "year": 1982}, {"A": 0.282, "PA": 616, "B": 0.239, "name": "baked002", "year": 1983}, {"A": 0.343, "PA": 288, "B": 0.226, "name": "baked002", "year": 1984}, {"A": 0.299, "PA": 396, "B": 0.23, "name": "baked002", "year": 1985}, {"A": 0.275, "PA": 271, "B": 0.206, "name": "baked002", "year": 1986}, {"A": 0.301, "PA": 369, "B": 0.286, "name": "bakef102", "year": 1921}, {"A": 0.274, "PA": 258, "B": 0.278, "name": "bakef102", "year": 1922}, {"A": 0.259, "PA": 234, "B": 0.237, "name": "bakef103", "year": 1945}, {"A": 0.233, "PA": 439, "B": 0.294, "name": "bakef103", "year": 1947}, {"A": 0.205, "PA": 411, "B": 0.222, "name": "bakef103", "year": 1948}, {"A": 0.232, "PA": 474, "B": 0.289, "name": "bakef103", "year": 1949}, {"A": 0.397, "PA": 223, "B": 0.234, "name": "bakef103", "year": 1950}, {"A": 0.255, "PA": 298, "B": 0.268, "name": "bakef103", "year": 1952}, {"A": 0.307, "PA": 603, "B": 0.244, "name": "bakeg101", "year": 1954}, {"A": 0.256, "PA": 681, "B": 0.276, "name": "bakeg101", "year": 1955}, {"A": 0.29, "PA": 605, "B": 0.229, "name": "bakeg101", "year": 1956}, {"A": 0.236, "PA": 458, "B": 0.296, "name": "bakeg101", "year": 1957}, {"A": 0.323, "PA": 333, "B": 0.22, "name": "bakej001", "year": 2008}, {"A": 0.256, "PA": 248, "B": 0.321, "name": "bakej001", "year": 2009}, {"A": 0.281, "PA": 224, "B": 0.26, "name": "bakej001", "year": 2010}, {"A": 0.311, "PA": 225, "B": 0.212, "name": "bakej001", "year": 2014}, {"A": 0.27, "PA": 233, "B": 0.329, "name": "bakej002", "year": 2008}, {"A": 0.279, "PA": 423, "B": 0.26, "name": "bakej002", "year": 2009}, {"A": 0.189, "PA": 214, "B": 0.285, "name": "bakej002", "year": 2012}, {"A": 0.304, "PA": 333, "B": 0.24, "name": "bakop001", "year": 1998}, {"A": 0.281, "PA": 246, "B": 0.234, "name": "bakop001", "year": 1999}, {"A": 0.235, "PA": 251, "B": 0.217, "name": "bakop001", "year": 2000}, {"A": 0.219, "PA": 338, "B": 0.215, "name": "bakop001", "year": 2008}, {"A": 0.258, "PA": 488, "B": 0.231, "name": "balbs001", "year": 1984}, {"A": 0.226, "PA": 662, "B": 0.262, "name": "balbs001", "year": 1985}, {"A": 0.196, "PA": 562, "B": 0.257, "name": "balbs001", "year": 1986}, {"A": 0.234, "PA": 425, "B": 0.18, "name": "balbs001", "year": 1987}, {"A": 0.221, "PA": 440, "B": 0.247, "name": "balbs001", "year": 1988}, {"A": 0.241, "PA": 334, "B": 0.231, "name": "balbs001", "year": 1989}, {"A": 0.243, "PA": 307, "B": 0.131, "name": "balbs001", "year": 1990}, {"A": 0.296, "PA": 684, "B": 0.281, "name": "baldr001", "year": 2003}, {"A": 0.324, "PA": 565, "B": 0.238, "name": "baldr001", "year": 2004}, {"A": 0.277, "PA": 387, "B": 0.329, "name": "baldr001", "year": 2006}, {"A": 0.211, "PA": 260, "B": 0.194, "name": "balew001", "year": 2008}, {"A": 0.21, "PA": 295, "B": 0.255, "name": "balew001", "year": 2009}, {"A": 0.292, "PA": 672, "B": 0.302, "name": "bancd101", "year": 1920}, {"A": 0.307, "PA": 697, "B": 0.33, "name": "bancd101", "year": 1921}, {"A": 0.331, "PA": 745, "B": 0.309, "name": "bancd101", "year": 1922}, {"A": 0.301, "PA": 513, "B": 0.306, "name": "bancd101", "year": 1923}, {"A": 0.269, "PA": 362, "B": 0.288, "name": "bancd101", "year": 1924}, {"A": 0.303, "PA": 560, "B": 0.337, "name": "bancd101", "year": 1925}, {"A": 0.365, "PA": 540, "B": 0.266, "name": "bancd101", "year": 1926}, {"A": 0.255, "PA": 427, "B": 0.227, "name": "bancd101", "year": 1927}, {"A": 0.253, "PA": 591, "B": 0.238, "name": "bancd101", "year": 1928}, {"A": 0.3, "PA": 403, "B": 0.241, "name": "bancd101", "year": 1929}, {"A": 0.163, "PA": 212, "B": 0.26, "name": "bandc001", "year": 1982}, {"A": 0.285, "PA": 260, "B": 0.295, "name": "bandc001", "year": 1984}, {"A": 0.277, "PA": 290, "B": 0.258, "name": "bandc001", "year": 1986}, {"A": 0.26, "PA": 229, "B": 0.184, "name": "bandc001", "year": 1987}, {"A": 0.28, "PA": 231, "B": 0.186, "name": "bandj001", "year": 2016}, {"A": 0.238, "PA": 674, "B": 0.262, "name": "bands101", "year": 1968}, {"A": 0.307, "PA": 734, "B": 0.251, "name": "bands101", "year": 1969}, {"A": 0.276, "PA": 636, "B": 0.25, "name": "bands101", "year": 1970}, {"A": 0.256, "PA": 643, "B": 0.283, "name": "bands101", "year": 1971}, {"A": 0.233, "PA": 629, "B": 0.236, "name": "bands101", "year": 1972}, {"A": 0.258, "PA": 690, "B": 0.318, "name": "bands101", "year": 1973}, {"A": 0.226, "PA": 603, "B": 0.26, "name": "bands101", "year": 1974}, {"A": 0.246, "PA": 658, "B": 0.211, "name": "bands101", "year": 1975}, {"A": 0.197, "PA": 640, "B": 0.28, "name": "bands101", "year": 1976}, {"A": 0.255, "PA": 666, "B": 0.244, "name": "bands101", "year": 1977}, {"A": 0.271, "PA": 629, "B": 0.299, "name": "bands101", "year": 1978}, {"A": 0.258, "PA": 543, "B": 0.232, "name": "bands101", "year": 1979}, {"A": 0.217, "PA": 291, "B": 0.176, "name": "bands101", "year": 1980}, {"A": 0.254, "PA": 249, "B": 0.23, "name": "bankb001", "year": 1999}, {"A": 0.3, "PA": 650, "B": 0.25, "name": "banke101", "year": 1954}, {"A": 0.316, "PA": 645, "B": 0.278, "name": "banke101", "year": 1955}, {"A": 0.287, "PA": 595, "B": 0.303, "name": "banke101", "year": 1956}, {"A": 0.292, "PA": 673, "B": 0.275, "name": "banke101", "year": 1957}, {"A": 0.307, "PA": 682, "B": 0.318, "name": "banke101", "year": 1958}, {"A": 0.29, "PA": 671, "B": 0.318, "name": "banke101", "year": 1959}, {"A": 0.273, "PA": 677, "B": 0.27, "name": "banke101", "year": 1960}, {"A": 0.273, "PA": 573, "B": 0.282, "name": "banke101", "year": 1961}, {"A": 0.272, "PA": 657, "B": 0.265, "name": "banke101", "year": 1962}, {"A": 0.227, "PA": 484, "B": 0.226, "name": "banke101", "year": 1963}, {"A": 0.257, "PA": 636, "B": 0.27, "name": "banke101", "year": 1964}, {"A": 0.284, "PA": 680, "B": 0.247, "name": "banke101", "year": 1965}, {"A": 0.273, "PA": 554, "B": 0.27, "name": "banke101", "year": 1966}, {"A": 0.265, "PA": 615, "B": 0.285, "name": "banke101", "year": 1967}, {"A": 0.245, "PA": 595, "B": 0.247, "name": "banke101", "year": 1968}, {"A": 0.25, "PA": 629, "B": 0.255, "name": "banke101", "year": 1969}, {"A": 0.243, "PA": 247, "B": 0.261, "name": "banke101", "year": 1970}, {"A": 0.261, "PA": 630, "B": 0.287, "name": "banna001", "year": 1977}, {"A": 0.254, "PA": 560, "B": 0.311, "name": "banna001", "year": 1979}, {"A": 0.269, "PA": 443, "B": 0.297, "name": "banna001", "year": 1980}, {"A": 0.298, "PA": 250, "B": 0.228, "name": "banna001", "year": 1981}, {"A": 0.234, "PA": 398, "B": 0.293, "name": "banna001", "year": 1982}, {"A": 0.268, "PA": 422, "B": 0.262, "name": "banna001", "year": 1983}, {"A": 0.19, "PA": 239, "B": 0.241, "name": "barar001", "year": 2003}, {"A": 0.3, "PA": 389, "B": 0.205, "name": "barar001", "year": 2004}, {"A": 0.275, "PA": 450, "B": 0.232, "name": "barar001", "year": 2005}, {"A": 0.271, "PA": 371, "B": 0.243, "name": "barar001", "year": 2006}, {"A": 0.246, "PA": 377, "B": 0.251, "name": "barar001", "year": 2008}, {"A": 0.25, "PA": 460, "B": 0.203, "name": "barar001", "year": 2009}, {"A": 0.278, "PA": 339, "B": 0.203, "name": "barar001", "year": 2010}, {"A": 0.203, "PA": 337, "B": 0.256, "name": "barar001", "year": 2011}, {"A": 0.217, "PA": 361, "B": 0.195, "name": "barar001", "year": 2012}, {"A": 0.226, "PA": 343, "B": 0.238, "name": "barbb001", "year": 1992}];

	myData.sort(function(a,b) {return b['PA']-a['PA'];});
	dataA = myData.slice(0,100);
	console.log(dataA);
	var dataAA = [['A','B']];
	for (var i=0;i<dataA.length;i++){
		var thisRow = [dataA[i]['A'],dataA[i]['B']];
		dataAA.push(thisRow);
	}
  var data = google.visualization.arrayToDataTable(dataAA);


  var options = {
	title: 'Correlation between life expectancy, fertility rate ' +
		   'and population of some world countries (2010)',
	hAxis: {title: 'A'},
	vAxis: {title: 'B'},
	bubble: {textStyle: {fontSize: 1}}
  };

  var chart = new google.visualization.ScatterChart(document.getElementById('series_chart_div'));
  chart.draw(data, options);
}


var firstYear = 0;
var newYear = firstYear;
var yearInterval;
var nLeaders = 10;
var raceData = {};
var allY;

var svg;

function loadRace(rawData) {
		console.log(rawData);
		raceData = {};
		for (var i=0;i<rawData.length;i++) {
			maxII = i-(i%10);
			if (i%10 == 0){raceData[rawData[i]['Split']]=[];}
			lastRank = 11;
			if (parseInt(rawData[i]['Split']) >= 1) {
				for (var ii=0;ii<10;ii++) {
					if (raceData[parseInt(rawData[i]['Split'])-1][ii]['id'] == rawData[i]['name']+rawData[i]['year'] && raceData[parseInt(rawData[i]['Split'])-1][ii]['year'] == rawData[i]['year']) {
						lastRank = ii+1;
						break;
					}
				}
			}
			thisRow = {'year':rawData[i]['year'],'id':rawData[i]['name']+rawData[i]['year'],'war':rawData[i]['N'],'rank':(i%10)+1,'last':lastRank,'lastwar':rawData[i]['LN']};
			
			raceData[rawData[i]['Split']].push(thisRow);
		}
		allY = [];
		for (var i=0;i<nLeaders + 1;i++) {
			allY.push(nLeaders + 1 - i);
		}
		//console.log(allY);
		console.log(raceData);
		createRace(raceData);

}

function createRace(data){
		
	// set the dimensions and margins of the graph
	var margin = {top: 20, right: 20, bottom: 30, left: 40},
    width = 600 - margin.left - margin.right,
    height = 400 - margin.top - margin.bottom;

	svg = d3.select("#barchart-location")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", 
          "translate(" + margin.left + "," + margin.top + ")");
          
	// set the ranges
	var y = d3.scaleBand()
          .range([height, 0])
          .padding(0.1);

	var x = d3.scaleLinear()
          .range([0, width]);
          
	// append the svg object to the body of the page
	// append a 'group' element to 'svg'
	// moves the 'group' element to the top left margin


  // format the data
  data[firstYear].forEach(function(d) {
    d.war = +d.war;
  });

  // Scale the range of the data in the domains
  x.domain([0, d3.max(data[199], function(d){ return d.war; })])
  y.domain(allY);
  //y.domain([0, d3.max(data, function(d) { return d.sales; })]);

  // append the rectangles for the bar chart
  svg.selectAll(".bar")
      .data(data[firstYear])
    .enter().append("rect")
      .attr("class", "bar")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("width", function(d) {return x(d.war); } )
      .attr("y", function(d) { return y(d.rank); })
      .attr("height", y.bandwidth());

  svg.selectAll(".barText")
      .data(data[firstYear])
    .enter().append("text")
      .attr("class", "barText")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("y", function(d) { return y(d.rank) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.war); })
      .attr("height", y.bandwidth())
      .text(function(d) { return d.id; });

  // add the x Axis
  svg.append("g")
  	  .attr('id','xAxis')
      .attr("transform", "translate(0," + height + ")")
      .call(d3.axisBottom(x));

  // add the y Axis
  svg.append("g")
  	 .attr('id','yAxis')
      .call(d3.axisLeft(y));


	
    
	
}


function pressButton() {
	yearInterval = setInterval(function(){ updateRace(500); }, 600);
}
function updateRace(duration) {
	
	newYear += 1;
	if (newYear >= 199){
		clearInterval(yearInterval);
		
	}

	
	var margin = {top: 20, right: 20, bottom: 30, left: 40},
    width = 600 - margin.left - margin.right,
    height = 400 - margin.top - margin.bottom;
  // format the data
  raceData[newYear].forEach(function(d) {
    d.war = +d.war;
  });
  
	// set the ranges
	var y = d3.scaleBand()
          .range([height, 0])
          .padding(0.1);

	var x = d3.scaleLinear()
          .range([0, width]);
	// Scale the range of the data in the domains
  x.domain([0, d3.max(raceData[199], function(d){ return d.war; })])
  y.domain( allY );
  //y.domain([0, d3.max(data, function(d) { return d.sales; })]);
  
  svg.selectAll(".bar")
      .data(raceData[newYear])
    .enter().append("rect")
      .attr("class", "bar")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("width", function(d) {return 0; } )
      .attr("y", function(d) { return y.bandwidth(); })
      .attr("height", y.bandwidth());
      
  svg.selectAll(".bar")
      .data(raceData[newYear])
    .exit().remove();

	svg.selectAll(".barText")
      .data(raceData[newYear])
    .exit().remove();
    
	svg.selectAll(".barText")
      .data(raceData[newYear])
    .enter().append("text")
      .attr("class", "barText");
      
  svg.selectAll(".barText")
      .data(raceData[newYear])
    .exit().remove();
      
  // append the rectangles for the bar chart
  svg.selectAll("rect")
      .data(raceData[newYear])
      .attr("width", function(d) {return x(d.lastwar); } )
      .attr("y", function(d) { if (d.id == "Ken Griffey") {console.log(d)}; return y(d.last); })
      .transition()
      .duration(duration)
      .attr("width", function(d) {return x(d.war); } )
      .attr("y", function(d) { return y(d.rank); });
  
  svg.selectAll("text")
      .data(raceData[newYear])
      .attr("y", function(d) { return y(d.last) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.lastwar); })
      .attr("height", y.bandwidth())
      .text(function(d) { return d.id; })
      .transition()
      .duration(duration)
      .attr("y", function(d) { return y(d.rank) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.war); })
      .attr("height", y.bandwidth())
      
      

	var yAxis = d3.select("#xAxis")
      .call(d3.axisBottom(x));
  // add the y Axis
  var yAxis = d3.select("#yAxis")
      .call(d3.axisLeft(y));
}

function handleClick(d, i) {
	if (splitcol > -1) {
		createLeaderboard([d[splitcol]]);
		var ref = document.getElementById('splitrow_'+i);
	
		var popup = document.getElementById('fullSplits');
		
		popup.style.display = 'inline-block';
	
	
		var popper = new Popper(ref,popup,{
			placement: 'bottom',
						
		});
	}
	
}


