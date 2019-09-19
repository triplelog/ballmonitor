
    	
var teamData = [];
var careerData;
var bestGames = [];
var allBatterData = [];
var allPitcherData = [];
var gameData = [];
var pitcherGameData = [];
var teamid = window.location.search.substring(4).toUpperCase();
var year = 2016;

if (teamid.length > 6) {
	year = parseInt(teamid.substring(3));
}
if (teamid.length > 3) {
	teamid = teamid.substring(0,3);
}
console.log(teamid);

function updateSlider(value) {
	addGame(value);
}

var teamData = {};
var chosenTeam = '';
var myValue = 0;
var lgavg = 5;
var teams = {};
var myData = {};
var leagues = ['NL','AL'];
var divisions = ['W','C','E'];
var fullSchedule = {};
var dateList = [];
var myLeague = 'ML';
var myDivision = 'WCE';
var dateLen = Object.keys(fullSchedule).length;
for (var i=0;i<dateLen;i++) {
	dateList.push([Object.keys(fullSchedule)[i],0]);
}



d3.csv('retrosheet-master/retrosheet/eventfiles/'+year+'/'+year+teamid+'/allbatterboxes.csv').then(function(data) {
	gameData = data.slice();
	Object.freeze(gameData);
	data = data.sort(function(a, b){ 
		if (a.id > b.id) {return 1;}
		else if (b.id > a.id) {return -1;}
		else {return 0;}
	});
	makeStats(data,'batter');
	createBatterStats();
	
});

d3.csv('retrosheet-master/retrosheet/eventfiles/'+year+'/'+year+teamid+'/allpitcherboxes.csv').then(function(data) {
	pitcherGameData = data.slice();
	Object.freeze(pitcherGameData);
	data = data.sort(function(a, b){ 
		if (a.id > b.id) {return 1;}
		else if (b.id > a.id) {return -1;}
		else {return 0;}
	});
	makeStats(data,'pitcher');
	createPitcherStats();
});


d3.csv("data/teams/"+teamid+"/"+year+"schedule.csv").then(function(data) {
  //console.log(data);
  var scheduleData = [];
  for (var i=0;i<data.length;i++) {
  	date = data[i].id.substring(7,11);
  	if (parseInt(data[i].ra) > parseInt(data[i].rs)) {
		result = 'L '+data[i].ra+'-'+data[i].rs
	}
	else if (parseInt(data[i].ra) < parseInt(data[i].rs)) {
		result = 'W '+data[i].rs+'-'+data[i].ra
	}
	else {
		result = 'T '+data[i].ra+'-'+data[i].rs
	}
  	if (data[i].loc == 'H') {
  		scheduleData.push([data[i].id,'vs. '+data[i].opp,data[i].starter,result]);
  	}
  	else {
  		scheduleData.push([data[i].id,'@ '+data[i].opp,data[i].starter,result]);
  	}
  }
  createSchedule(scheduleData);

});

d3.json("data/years/"+year+"Data.json").then(function(data) {
	leagues = data['leagues'];
	divisions = data['divisions'];
	fullSchedule = data['games'];
	teams = data['teams'];
	dateList = [];
	dateLen = Object.keys(fullSchedule).length;
	
	var initialDate = dateLen;
	
	
	for (var i=0;i<dateLen;i++) {
		dateList.push([Object.keys(fullSchedule)[i],0]);
	}
	
	
	document.getElementById('standingsSlider').value = initialDate;
	createStandings(year);
	updateSlider(initialDate);
  
});
	
function makeStats(data,ptype) {
  var stats;
  if (ptype == 'batter') {
  	stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
  }
  else {
  	stats = ['IPouts','H','BB','R','ER','PC','K'];
  }
  var playerData = {};
  fullTeamData = {};
  for (var stat=0;stat<stats.length;stat++){
	  fullTeamData[stats[stat]] = 0;
  }
  var currentPlayer = '';
  var gamesLength = data.length;
  for (var i=0;i<gamesLength;i++) {
  		for (var stat=0;stat<stats.length;stat++){
  			fullTeamData[stats[stat]] += parseInt(data[i][stats[stat]]);
  		}
  		
  		if (data[i].id != currentPlayer) {
  			currentPlayer = data[i].id;
  			playerData[currentPlayer] = {};
  			
  			for (var stat=0;stat<stats.length;stat++){
  				playerData[currentPlayer][stats[stat]] = parseInt(data[i][stats[stat]]);
  			}
  		}
  		else {
			
  			for (var stat=0;stat<stats.length;stat++){
  				playerData[currentPlayer][stats[stat]] += parseInt(data[i][stats[stat]]);
  			}
  		}
		
  }
  var players = Object.keys(playerData);

  for (var player=0;player<players.length;player++) {
  		var thisPlayer = [players[player]];

		for (var stat=0;stat<stats.length;stat++){
			thisPlayer.push(playerData[players[player]][stats[stat]]);
		}
		if (ptype == 'batter') {
  			allBatterData.push(thisPlayer);
  		}
  		else {
  			allPitcherData.push(thisPlayer);
  		}
  }
  if (ptype == 'batter') {
	allBatterData.sort(function(a,b) {return b[1] - a[1];});
  }
  else {
  	allPitcherData.sort(function(a,b) {return b[1] - a[1];});
  }
  
}

function createBatterStats() {
	var columns = ['player','PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
    
	var table = d3.select('#battingStats')
						.append('table').attr('class','stats_table sm_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','battingStatsBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(allBatterData)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d) { return d; });
}

function createPitcherStats() {
	var columns = ['player','IP','H','BB','R','ER','PC','K'];
    
	var table = d3.select('#pitchingStats')
						.append('table').attr('class','stats_table sm_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','pitchingStatsBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(allPitcherData)
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

function createSchedule(data) {
	var columns = ['date','opp','starter','res'];
    
	var table = d3.select('#schedule')
						.append('table').attr('class','sm_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','scheduleBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(data)
		.enter()
	  .append('tr')
	  .attr('id',function(d) {return d[0];})
	  .attr('style', function(d) {
	  	rs = parseInt(d[3].split(' ')[1].split('-')[0]);
	  	ra = parseInt(d[3].split(' ')[1].split('-')[1]);
	  	if (d[3].split(' ')[0] == 'L') {
			redC = 255;
			greenC = 0;
			blueC = 0;
	  	}
	  	else if (d[3].split(' ')[0] == 'W') {
			redC = 0;
			greenC = 255;
			blueC = 0;
	  	}
	  	else {
			redC = 255;
			greenC = 255;
			blueC = 255;
	  	}
	  	alphaC = Math.log(Math.abs(rs-ra)+1)/Math.log(25);
	  	
	  	return 'background-color: rgba('+redC+','+greenC+','+blueC+','+alphaC+');'
	  })
	  .on('click', function(d) {clickedGame(d[0]);});

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d, i) { 
	  	if (i != 0) {return d;}
	  	else {return parseInt(d.substring(7,9))+'/'+parseInt(d.substring(9,11));}
	   });
}

function clickedGame(gameid) {
	// ADD LINESCORE and game info to top
	var batterGameStats = [];
	var pitcherGameStats = [];
	var stats = ['PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
	for (var i=0;i<gameData.length;i++) {
		if (gameData[i].game == gameid) {
			var thisRow = [gameData[i].id];
			var thisSum = 0;
			for (var ii=0;ii<stats.length;ii++) {
				thisRow.push(gameData[i][stats[ii]]);
				thisSum += parseInt(gameData[i][stats[ii]]);
			}
			if (thisSum > 0) {
				batterGameStats.push(thisRow);
			}
		}
	}
	var pstats = ['IPouts','H','BB','R','ER','PC','K'];
	for (var i=0;i<pitcherGameData.length;i++) {
		if (pitcherGameData[i].game == gameid) {
			var thisRow = [pitcherGameData[i].id];
			for (var ii=0;ii<pstats.length;ii++) {
				thisRow.push(pitcherGameData[i][pstats[ii]]);
			}
			pitcherGameStats.push(thisRow);
		}
	}
	var columns = ['player','PA','AB','H','BB','R','RBI','K','1B','2B','3B','HR','HBP','SB','CS'];
	
	var ref = document.getElementById(gameid);
	var popup = document.getElementById('boxscore');
	popup.style.display = "inline-block";
	popup.style.background = "white";
	popup.innerHTML = '';
	
	var table = d3.select('#boxscore')
						.append('table').attr('class','stats_table sm_table');

	var thead = table.append('thead');
	var tbody = table.append('tbody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(batterGameStats)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d) { if (d != 0) {return d} else {return ''}; });
	
	columns = ['player','IP','H','BB','R','ER','PC','K'];
	table = d3.select('#boxscore')
						.append('table').attr('class','stats_table sm_table');

	thead = table.append('thead');
	tbody = table.append('tbody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(pitcherGameStats)
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
	  
	var popper = new Popper(ref,popup,{
		placement: 'left',
						
	});
}

function createTeamStats() {
	var columns = ['year','PA','AB','H','BB','R','RBI','K','HR','HBP','1B','2B','3B'];
    
	var table = d3.select('#playerStats')
						.append('table').attr('class','stats_table');

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
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	  .text(function (d) { return d; });
}

function createStandings(year){

	var slider = d3.select("#standingsSlider")
					.attr('max',dateLen)
					.on('input', function() {updateSlider(this.value)});
	
	teamData = {};
	nTeams = 0;
	
	
	for (var i=0; i < leagues.length; i++) {
		for (var ii=0;ii<divisions.length;ii++) {
			myData[leagues[i]+divisions[ii]]=[];
			for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {
				if (teams[leagues[i]][divisions[ii]][iii] == teamid) {myLeague = leagues[i]; myDivision = divisions[ii];}
				teamData[teams[leagues[i]][divisions[ii]][iii]] = {'wins':0,'losses':0,'runs':0,'allowed':0,'elo':1500,'last10':[]};
				
				teamrow = [teams[leagues[i]][divisions[ii]][iii],0,0,0,'-',0,0,'0-0'];
				myData[leagues[i]+divisions[ii]].push(teamrow);
				
			}
			if (leagues[i] == myLeague && divisions[ii] == myDivision) {
				createDivision(leagues[i]+divisions[ii],leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
			}
		}
	}
	
	

    
}

function addGame(dateIndex){

	for (var di=0;di<dateIndex;di++){
		if (dateList[di][1]<1) {
			var schedule = fullSchedule[dateList[di][0]];
	
			for (var i=0;i<schedule.length;i++){

				runs1 = schedule[i]['vruns'];
				runs2 = schedule[i]['hruns'];
				var k = 15.0;
				var probHomeWin = 1.0/(1.0+ Math.pow(10.0,(teamData[schedule[i]['vteam']]['elo']-teamData[schedule[i]['hteam']]['elo'])/400.0));
				if (runs1>runs2){
					teamData[schedule[i]['vteam']]['wins']+=1;
					teamData[schedule[i]['hteam']]['losses']+=1;
					teamData[schedule[i]['vteam']]['last10'].push(1);
					teamData[schedule[i]['hteam']]['last10'].push(0);
					teamData[schedule[i]['vteam']]['elo'] = teamData[schedule[i]['vteam']]['elo'] + k*probHomeWin;
					teamData[schedule[i]['hteam']]['elo'] = teamData[schedule[i]['hteam']]['elo'] - k*probHomeWin;
				}
				else if (runs2>runs1){
					teamData[schedule[i]['hteam']]['wins']+=1;
					teamData[schedule[i]['vteam']]['losses']+=1;
					teamData[schedule[i]['vteam']]['last10'].push(0);
					teamData[schedule[i]['hteam']]['last10'].push(1);
					teamData[schedule[i]['vteam']]['elo'] = teamData[schedule[i]['vteam']]['elo'] - k*(1-probHomeWin);
					teamData[schedule[i]['hteam']]['elo'] = teamData[schedule[i]['hteam']]['elo'] + k*(1-probHomeWin);
				}
				teamData[schedule[i]['vteam']]['runs']+=runs1;
				teamData[schedule[i]['hteam']]['allowed']+=runs1;
				teamData[schedule[i]['hteam']]['runs']+=runs2;
				teamData[schedule[i]['vteam']]['allowed']+=runs2;
				
			}
			
			dateList[di][1]=1;
		}
	}
	for (var di=dateIndex;di<dateLen;di++){
		if (dateList[di][1]==1) {
			var schedule = fullSchedule[dateList[di][0]];
	
			for (var i=0;i<schedule.length;i++){

				runs1 = schedule[i]['vruns'];
				runs2 = schedule[i]['hruns'];
				
				if (runs1>runs2){
					teamData[schedule[i]['vteam']]['wins']-=1;
					teamData[schedule[i]['hteam']]['losses']-=1;
					
				}
				else if (runs2>runs1){
					teamData[schedule[i]['hteam']]['wins']-=1;
					teamData[schedule[i]['vteam']]['losses']-=1;
				}
				teamData[schedule[i]['vteam']]['runs']-=runs1;
				teamData[schedule[i]['hteam']]['allowed']-=runs1;
				teamData[schedule[i]['hteam']]['runs']-=runs2;
				teamData[schedule[i]['vteam']]['allowed']-=runs2;
				teamData[schedule[i]['vteam']]['last10'].splice(teamData[schedule[i]['vteam']]['last10'].length-1,1);
				teamData[schedule[i]['hteam']]['last10'].splice(teamData[schedule[i]['hteam']]['last10'].length-1,1);
			}
			
			dateList[di][1]=0;
		}
	}
	updateStandings();
	
}

function updateStandings() {
	myData = {};
	for (var i=0; i < leagues.length; i++) {
		for (var ii=0;ii<divisions.length;ii++) {
			myData[leagues[i]+divisions[ii]]=[];
			for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {

				teamrow = [teams[leagues[i]][divisions[ii]][iii],teamData[teams[leagues[i]][divisions[ii]][iii]]['wins'],teamData[teams[leagues[i]][divisions[ii]][iii]]['losses'],0,'-',teamData[teams[leagues[i]][divisions[ii]][iii]]['runs'],teamData[teams[leagues[i]][divisions[ii]][iii]]['allowed'],'0-0'];
				if (teamrow[1]+teamrow[2] > 0) {
					teamrow[3] = (teamrow[1]/(teamrow[1]+teamrow[2])).toFixed(3);
				}
				if (teamrow[5] > 0) {
					var expwp = 1.0/(1.0+Math.pow(teamrow[6]/teamrow[5],1.83));
					var expwins = Math.round(expwp * (teamrow[1]+teamrow[2])).toFixed(0);
					var explosses = (teamrow[1]+teamrow[2] - expwins).toFixed(0);
					teamrow[7] = expwins + '-' + explosses;
				}
				else {
					var expwp = 0.0;
					teamrow[7] =  '0-' + teamrow[2];
				}
				myData[leagues[i]+divisions[ii]].push(teamrow);
				
			}
			myData[leagues[i]+divisions[ii]].sort(function(a, b){return b[1] - b[2] - a[1] + a[2]});
			maxWL = myData[leagues[i]+divisions[ii]][0][1]-myData[leagues[i]+divisions[ii]][0][2];
			for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {
				if (myData[leagues[i]+divisions[ii]][iii][1]-myData[leagues[i]+divisions[ii]][iii][2] >= maxWL) {
					myData[leagues[i]+divisions[ii]][iii][4] = '-';
				}
				else {
					myData[leagues[i]+divisions[ii]][iii][4] = ((maxWL - (myData[leagues[i]+divisions[ii]][iii][1]-myData[leagues[i]+divisions[ii]][iii][2]))/2).toFixed(1);
				}
			}
			if (leagues[i] == myLeague && divisions[ii] == myDivision) {
				updateDivision(leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
			}
		}
	}
	
	
}


function createDivision(divID,divName,divData) {
	var columns = [divName,'W','L','PCT','GB','RS','RA','ExpW-L'];
    
	var leagueDiv = d3.select('#'+divID.substring(0,2))
						.append('div')
						.attr('classList','col col-lg-12')
						.attr('id', divID);
						
	var table = d3.select('#'+divID).append('table').attr('class','stats_table sm_table');
	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id',divID+'Body');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(divData)
		.enter()
	  .append('tr')
	  .attr('class', function (d) { if (d[0] == teamid) {return 'myTeam';} else {return '';} });

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	.attr('class',function (d) { 
		if (Array.isArray(d)) {
			return 'last10';
		}
		else {
			return 'otherCell';
		}
	  })
	  .text(function (d) { 
		if (Array.isArray(d)) {
			return '7'
		}
		else {
			return d 
		}
	  });
}

function updateDivision(divID,divData) {
	var tbody = d3.select('#'+divID+'Body');
	

	var rows = tbody.selectAll('tr')
		.data(divData)
		.attr('class', function (d) { if (d[0] == teamid) {return 'myTeam';} else {return '';} });

	  
	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
		.attr('class',function (d) { 
		if (Array.isArray(d)) {
			return 'last10';
		}
		else {
			return 'otherCell';
		}
	  })
	  .text(function (d) { 
		if (Array.isArray(d)) {
			var retString = '';
			for (var i=0;i<d.length;i++) {
				if (d[i] == 1) {
					retString += '✅';
				}
				else {
					retString += '❌';
				}
			}
			return retString;
		}
		else {
			return d 
		}
	  });
}
