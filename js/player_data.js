
var playerData = [];
var careerData;
var bestGames = [];
var playerid = window.location.search.substring(4);
var IPouts = 0;
var PAs = 0;
var pitchingData = {};
var battingData = {};
var gameMode = 'pitching';
var displayColumns = [0,1,2,3,4,5,6,10,12,19,20,21,22];

Promise.all([d3.csv("data/players/"+playerid+"battingstats.csv"), d3.csv("data/players/"+playerid+"pitchingstats.csv")]).then(function(data) {

	  pitchingData = data[1];
	  battingData = data[0];
	  
	  for (var i=0;i<pitchingData.length;i++) {
		IPouts += parseInt(pitchingData[i].IPouts);
	  }
  
	  for (var i=0;i<data[0].length;i++) {
		PAs += parseInt(data[0][i].PA);
	  }
	  
	  if (IPouts > PAs) {
		  pitchingData.sort(function(a, b){return a.date - b.date});
		  var columns = makeStats(pitchingData,'pitching');
		  findBestPitchingGames(pitchingData);

		  createPlayerStats();
		  createBestGames('pitching');
	  }
	  else {
	  	  gameMode = 'batting';
	  	  battingData.sort(function(a, b){return a.date - b.date});
		  var columns = makeStats(battingData,'batting');
		  findBestBattingGames(battingData);

		  createPlayerStats();
		  createBestGames('batting');
	  }

}).catch(function(err) {
	d3.csv("data/players/"+playerid+"battingstats.csv").then(function(data) {
		  gameMode = 'batting';
		  battingData = data;
		  battingData.sort(function(a, b){return a.date - b.date});
		  var columns = makeStats(battingData,'batting');
		  findBestBattingGames(battingData);

		  createPlayerStats();
		  createBestGames('batting');



	}).catch(function(err) {
		d3.csv("data/players/"+playerid+"pitchingstats.csv").then(function(data) {

			  pitchingData = data;

			  pitchingData.sort(function(a, b){return a.date - b.date});
			  var columns = makeStats(pitchingData,'pitching');
			  findBestPitchingGames(pitchingData);

			  createPlayerStats();
			  createBestGames('pitching');


		}).catch(function(err) {
			// dispatch a failure and throw error
			console.log('hhhh', err);

		});

	});

});

var leaderData = [];
d3.csv("data/players/leaders/"+playerid+".csv").then(function(data) {

	  leaderData = [];
	  for (var i=0;i<data.length;i++){
	  	leaderData.push([data[i]['stat'],data[i]['#'],data[i]['rank'],data[i]['year']]);
	  }
	  makeLeaders(['stat','#','rank','year'],leaderData);

}).catch(function(err) {
	var element = document.getElementById('leaderboardDiv');
	element.parentNode.removeChild(element);
	console.log('hjkkl');
})


function makeStats(data,borp,newstats=[]) {

  //var columns = ['Year','PA','AB','H','BB','R','RBI','K','HR','HBP','1B','2B','3B','AVG','OBP','SLG','OPS'];
  //var stats = ['PA','AB','H','BB','R','RBI','K','HR','HBP','1B','2B','3B'];
  stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF'];
  
  var columns = ['Year'].concat(stats).concat(['AVG','OBP','SLG','OPS']);
  
  if (borp == 'pitching'){
  	columns = ['Year','IP','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB','FIP','ERA','FIP','ERA'];
  	stats = ['IPouts','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB','FIP','ERA','FIP','ERA'];
  }
  if (newstats.length>0){
  	columns = ['Year'].concat(newstats);
  }
  var yearData = {};
  careerData = {};
  playerData = [];
  for (var stat=0;stat<stats.length;stat++){
	  careerData[stats[stat]] = 0;
  }
  var currentYear = '';
  var gamesLength = data.length;
  for (var i=0;i<gamesLength;i++) {
  		for (var stat=0;stat<stats.length;stat++){
  			careerData[stats[stat]] += parseInt(data[i][stats[stat]]);
  		}
  		
  		if (data[i].date.substring(0,4) != currentYear) {
  			currentYear = data[i].date.substring(0,4);
  			yearData[currentYear] = {};
  			
  			for (var stat=0;stat<stats.length;stat++){
  				yearData[currentYear][stats[stat]] = parseInt(data[i][stats[stat]]);
  			}
  		}
  		else {

  			for (var stat=0;stat<stats.length;stat++){
  				yearData[currentYear][stats[stat]] += parseInt(data[i][stats[stat]]);
  			}
  		}
		
  }
  var years = Object.keys(yearData);
  for (var year=0;year<years.length;year++) {
  		var thisYear = [years[year]];

		for (var stat=1;stat<columns.length;stat++){
			if (columns[stat] == 'AVG' || columns[stat] == 'OBP' || columns[stat] == 'SLG' || columns[stat] == 'OPS' || columns[stat] == 'FIP' || columns[stat] == 'ERA') {
				thisYear.push(displayStat(computeStat(yearData[years[year]],columns[stat]),3));
			}
			else if (columns[stat] == 'IP') {
				thisYear.push(yearData[years[year]]['IPouts']);
			}
			else {
				thisYear.push(yearData[years[year]][columns[stat]]);
			}
		}

  		playerData.push(thisYear);
  }
  
    var careerTotals = ['Total'];
	
	for (var stat=1;stat<columns.length;stat++){
		if (columns[stat] == 'AVG' || columns[stat] == 'OBP' || columns[stat] == 'SLG' || columns[stat] == 'OPS' || columns[stat] == 'FIP' || columns[stat] == 'ERA') {
			careerTotals.push(displayStat(computeStat(careerData,columns[stat]),3));
		}
		else if (columns[stat] == 'IP') {
			careerTotals.push(careerData['IPouts']);
		}
		else {
			careerTotals.push(careerData[columns[stat]]);
		}
	}


    playerData.push(careerTotals);
  
  return columns;

}

function findBestBattingGames(data,stat='OPS') {
	var careerOPS; var stats;
	careerOPS = computeStat(careerData,stat,'batting');

  	stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF'];

  var gamesLength = data.length;
  bestGames = [];
  var maxGames = 10;
  for (var i=0;i<gamesLength;i++) {
  		var gameOPS = computeStat(data[i],stat,'batting');

  		var OPSAA = (gameOPS-careerOPS)*parseInt(data[i].PA);

  		if (bestGames.length > 0) {
  		
			if (OPSAA > bestGames[bestGames.length-1].score){
				for (var ii=0;ii<bestGames.length;ii++) {
					if (OPSAA > bestGames[ii].score) {
						bestGames.splice(ii,0,{'score':OPSAA,'data':data[i]});
						break;
					}
				}
				if (bestGames.length > maxGames) {
					bestGames = bestGames.slice(0,maxGames);
				}
			}
			else if (bestGames.length < maxGames) {
				bestGames.push({'score':OPSAA,'data':data[i]});
			}
		}
		else {
			bestGames.push({'score':OPSAA,'data':data[i]});
		}
		//if (data[i].date.substring(0,4) == '1987'){
		//	console.log(data[i]);
		//}

  }
  
 
}

function findBestPitchingGames(data,stat='FIP') {
	var careerFIP; var stats;
	careerFIP = computeStat(careerData,stat);
  	stats = ['IPouts','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB'];

  var gamesLength = data.length;
  bestGames = [];
  var maxGames = 10;
  for (var i=0;i<gamesLength;i++) {
  		var gameFIP = computeStat(data[i],stat);
  		var FIPAA = (gameFIP-careerFIP)*parseInt(data[i].IPouts)*-1;
  		if (bestGames.length > 0) {
  		
			if (FIPAA > bestGames[bestGames.length-1].score){
				for (var ii=0;ii<bestGames.length;ii++) {
					if (FIPAA > bestGames[ii].score) {
						bestGames.splice(ii,0,{'score':FIPAA,'data':data[i]});
						break;
					}
				}
				if (bestGames.length > maxGames) {
					bestGames = bestGames.slice(0,maxGames);
				}
			}
			else if (bestGames.length < maxGames) {
				bestGames.push({'score':FIPAA,'data':data[i]});
			}
		}
		else {
			bestGames.push({'score':FIPAA,'data':data[i]});
		}
		//if (data[i].date.substring(0,4) == '1987'){
		//	console.log(data[i]);
		//}
		
  }
  
 
}



function createPlayerStats() {
	
		
	baseColumns = ['Year'];
	if (gameMode.toLowerCase() == 'batting') {
		stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF','AVG','OBP','SLG','OPS'];
	}
	else {
		stats = ['IPouts','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB','FIP','ERA','FIP','ERA'];
	}
	for (var i=0;i<23;i++) {
		statcol = document.getElementById('stat'+i);
		statcol.innerHTML = stats[i];
		if (statcol.classList.contains('btn-primary')) { statcol.classList.remove("btn-primary");	}
		if (!statcol.classList.contains('disabled')) { statcol.classList.add("disabled");	}
		if (!statcol.classList.contains('btn-secondary')) { statcol.classList.add("btn-secondary");	}
	}
	for (var i=0;i<displayColumns.length;i++) {
		statcol = document.getElementById('stat'+displayColumns[i]);
		
		if (statcol.classList.contains('btn-secondary')) { statcol.classList.remove("btn-secondary");	}
		if (statcol.classList.contains('disabled')) { statcol.classList.remove("disabled");	}
		if (!statcol.classList.contains('btn-primary')) { statcol.classList.add("btn-primary");	}
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

  
	
    document.getElementById('playerStats').innerHTML = '';
	var table = d3.select('#playerStats')
						.append('table').attr('class','stats_table sm_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','playerStatsBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(playerData)
		.enter()
	  .append('tr');

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
	  .text(function (d,i ) {
	  	if (columns[i] == 'IP') {
			if (parseInt(d)%3 == 0) {
				return parseInt(parseInt(d)/3)
			}
			else if (parseInt(d)%3 == 1 && parseInt(d) > 3) {
				return parseInt(parseInt(d)/3) + ' ⅓';
			}
			else if (parseInt(d)%3 == 1) {
				return '⅓';
			}
			else if (parseInt(d)%3 == 2 && parseInt(d) > 3) {
				return parseInt(parseInt(d)/3) + ' ⅔';
			}
			else {
				return '⅔';
			}
		}  
		else {
			return d;
		}
	  });
}

function createBestGames(borp,update=false) {
	
	var columns = ['game','PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS','IBB','GIDP','INT','SH','SF'];
	if (borp == 'pitching'){ columns = ['Game','IP','H','BB','R','ER','PC','K','HR','1B','2B','3B','WP','HBP','PA','AB','BK','SH','SF','IBB'];}

    var gameData = [];
    for (var i=0;i<bestGames.length;i++){
    	var oneRow = [bestGames[i]['data'].date];
    	for (var ii=1;ii<columns.length;ii++) {
    		if (columns[ii] == 'IP'){oneRow.push(bestGames[i]['data']['IPouts']);}
    		else {
    			oneRow.push(bestGames[i]['data'][columns[ii]]);
    		}
    	}
    	gameData.push(oneRow);
    }
    if (update) {
    	document.getElementById('bestGames').innerHTML = '';
    }
	var table = d3.select('#bestGames')
						.append('table').attr('class','stats_table sm_table');
	

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','bestGamesBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(gameData)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d,i ) {
	  	if (columns[i] == 'IP') {
			if (parseInt(d)%3 == 0) {
				return parseInt(parseInt(d)/3)
			}
			else if (parseInt(d)%3 == 1 && parseInt(d) > 3) {
				return parseInt(parseInt(d)/3) + ' ⅓';
			}
			else if (parseInt(d)%3 == 1) {
				return '⅓';
			}
			else if (parseInt(d)%3 == 2 && parseInt(d) > 3) {
				return parseInt(parseInt(d)/3) + ' ⅔';
			}
			else {
				return '⅔';
			}
		}  
		else {
			return d;
		}
	  });
}

function makeLeaders(columns,data) {
	var table = d3.select('#leaderboards')
						.append('table').attr('class','stats_table sm_table');
	

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','leaderboardsBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(data)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d,i ) {
	  	return d;
	  })
	  .attr('onclick',function(d,i) {if (i==0) {return 'showleaders("'+d+'")'} else {return '';} });
}

function updateBest() {

	if (gameMode == 'batting') {
		findBestBattingGames(battingData,document.getElementById('bestFormula').value);
		createBestGames('batting',true);
	}
	else {
		findBestPitchingGames(pitchingData,document.getElementById('bestFormula').value);
		createBestGames('pitching',true);
	}

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
			if (statcol.classList.contains('btn-primary')) { statcol.classList.remove("btn-primary");	}
			if (!statcol.classList.contains('disabled')) { statcol.classList.add("disabled");	}
			if (!statcol.classList.contains('btn-secondary')) { statcol.classList.add("btn-secondary");	}
			
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
	createPlayerStats();
}



function showleaders(stat) {
	window.location = 'leaderboard.html?formula='+stat+'&borpL=B';
}


