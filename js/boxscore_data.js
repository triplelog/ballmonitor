

var linescoreData = [[{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7}],[{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':'x','pbp':4},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7}]]
var batterData = {'away':[],'home':[]};
var pitcherData = {'away':[],'home':[]};

var pbpData = [];
var gameid = window.location.search.substring(4);
var hometeam = gameid.substring(0,3);
var awayteam;
var year = gameid.substring(3,7);

function makeGame() {
	
	Promise.all([d3.json("retrosheet-master/retrosheet/eventfiles/"+year+"/"+year+hometeam+"/gamelogs.json"),d3.csv("retrosheet-master/retrosheet/eventfiles/"+year+"/"+year+hometeam+"/"+gameid+"batterbox.csv"),d3.csv("retrosheet-master/retrosheet/eventfiles/"+year+"/"+year+hometeam+"/"+gameid+"pitcherbox.csv"),d3.csv("retrosheet-master/retrosheet/eventfiles/"+year+"/"+year+hometeam+"/"+gameid+"plays.csv")]).then(function(data) {
	  document.getElementById('linescore-location').innerHTML = '';
	  document.getElementById('homeoff-location').innerHTML = '';
	  document.getElementById('awayoff-location').innerHTML = '';
	  document.getElementById('homepitcher-location').innerHTML = '';
	  document.getElementById('awaypitcher-location').innerHTML = '';
	  linescoreData = [[{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7}],[{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':'x','pbp':4},{'value':0,'pbp':7},{'value':0,'pbp':7},{'value':0,'pbp':7}]]
	  batterData = {'away':[],'home':[]};
	  pitcherData = {'away':[],'home':[]};
      pbpData = [];
	  
	  homeData = data[0];
	  var gameinfo = homeData[gameid];
	  var opponent = gameinfo.opp;
	  awayteam = opponent;
	  d3.json("retrosheet-master/retrosheet/eventfiles/"+year+"/"+year+opponent+"/gamelogs.json").then(function(awayData) {
	  	document.getElementById('right-sidebar').innerHTML = '';
		document.getElementById('left-sidebar').innerHTML = '';
		
		createGame(homeData,awayData,gameinfo);
	  });
  
  
	  batterLength = data[1].length;
	  for (var i=0;i<batterLength;i++) {
		  if (data[1][i].team=='0') {
			batterData['away'].push([data[1][i].id,data[1][i].PA,data[1][i].AB,data[1][i].H,data[1][i].BB,data[1][i].R,data[1][i].RBI,data[1][i].K]);
		  }
		  else if (data[1][i].team=='1') {
			batterData['home'].push([data[1][i].id,data[1][i].PA,data[1][i].AB,data[1][i].H,data[1][i].BB,data[1][i].R,data[1][i].RBI,data[1][i].K]);
		  }
	  }
	  createBatters('away');
	  createBatters('home');
  
	  pitcherLength = data[2].length;
	  for (var i=0;i<pitcherLength;i++) {
		  if (data[2][i].team=='0') {
			pitcherData['away'].push([data[2][i].id,data[2][i].IPouts,data[2][i].R,data[2][i].ER,data[2][i].H,data[2][i].BB,data[2][i].K,data[2][i].PC]);
		  }
		  else if (data[2][i].team=='1') {
			pitcherData['home'].push([data[2][i].id,data[2][i].IPouts,data[2][i].R,data[2][i].ER,data[2][i].H,data[2][i].BB,data[2][i].K,data[2][i].PC]);
		  }
	  }
	  createPitchers('away');
	  createPitchers('home');

	  var pbpLength = data[3].length;
	  linescoreData = [[{'value':awayteam,'pbp':-1}],[{'value':hometeam,'pbp':-1}]];
	  var currentTeam = '1';
	  var halfRuns = 0;
	  var halfIndex = -1;
	  var currentouts = 0;
	  for (var i=1;i<pbpLength;i++) {
		  if (data[3][i].team == '0' && currentTeam == '1') {
			halfRuns = 0;
			halfIndex += 1;
			linescoreData[0].push({'value':0,'pbp':halfIndex});
			pbpData.push([]);
			currentouts = 0;
		  }
		  else if (data[3][i].team == '1' && currentTeam == '0') {
			halfRuns = 0;
			halfIndex += 1;
			linescoreData[1].push({'value':0,'pbp':halfIndex});
			pbpData.push([]);
			currentouts = 0;
		  }
		  if (parseInt(data[3][i].play_runs) > 0) {
			halfRuns += parseInt(data[3][i].play_runs);
			linescoreData[halfIndex%2][parseInt(halfIndex/2)+1].value = halfRuns;
		  }
		  
		  //data[3][i]['pitcher'],data[3][i]['play_outs']
		  pbpData[halfIndex].push([[data[3][i]['on-1'],data[3][i]['on-2'],data[3][i]['on-3']],data[3][i].play_str,data[3][i].advance_str,data[3][i].count_on_batter,currentouts]);
	  	  
	  	  if (parseInt(data[3][i].play_outs) > 0) {
			currentouts += parseInt(data[3][i].play_outs);
		  }
	  
		  currentTeam = data[3][i].team;
	  }
	  createLinescore();
	  updateLinescore();
	});
}

function createLinescore(){

	var runtotals = [0,0];
	
	for (var i=1;i<linescoreData[0].length;i++) {
    	runtotals[0] += linescoreData[0][i].value;
    }
    for (var i=1;i<linescoreData[1].length;i++) {
    	runtotals[1] += linescoreData[1][i].value;
    }
    var columns = ['',1,2,3,4,5,6,7,8,9];
    for (var i=10;i<linescoreData[0].length;i++) {
    	columns.push(i);
    }
    for (var i=linescoreData[0].length;i<10;i++) {
    	linescoreData[0].push({'value':'X','pbp':i*2-2});
    }
    for (var i=linescoreData[1].length;i<10;i++) {
    	linescoreData[1].push({'value':'X','pbp':i*2-1});
    }
    columns.push('R');
    columns.push('H');
    linescoreData[0].push({'value':runtotals[0],'pbp':-1});
    linescoreData[1].push({'value':runtotals[1],'pbp':-1});
    	
	var table = d3.select('#linescore-location').append('table');
	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id','linescoreBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });

	var rows = tbody.selectAll('tr')
		.data(linescoreData)
		.enter()
	  .append('tr');

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	.attr('id',function(d,i) {return 'pbpHalf_'+d.pbp;});
	
}



function updateLinescore() {
	
	var tbody = d3.select('#linescoreBody');
	

	var rows = tbody.selectAll('tr')
		.data(linescoreData);

	  
	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .text(function (d) { return d['value'] })
	  .on('click', function(d,i) {clickedLinescore(d.pbp);});
}

function clickedLinescore(i) {
	var ref = document.getElementById('pbpHalf_'+i);
	
	var popup = document.getElementById('linescorePBP');
	popup.removeEventListener("click", hidePopup);
	popup.innerHTML = "<div x-arrow></div>";
	var nplays = pbpData[i].length;
	for (var ii=0;ii<nplays;ii++) {
		popup.appendChild(addPBProw(pbpData[i][ii][0],pbpData[i][ii][1],pbpData[i][ii][2],pbpData[i][ii][3],pbpData[i][ii][4]));
	}
	popup.style.display = 'inline-block';
	popup.addEventListener("click", hidePopup);
	
	var popper = new Popper(ref,popup,{
		placement: 'bottom',
						
	});
}

function hidePopup() {
	var popup = document.getElementById('linescorePBP');
	popup.style.display = 'none';
}

function addPBProw(situation,play_str, advance_str, count, num_outs) {
	var firstFill = 'white';
	var secondFill = 'white';
	var thirdFill = 'white';
	if (situation[0].length > 0) {firstFill = 'red';}
	if (situation[1].length > 0) {secondFill = 'red';}
	if (situation[2].length > 0) {thirdFill = 'red';}

	var balls = count.substring(0,1);
	var strikes = count.substring(1,2);
	var outs = num_outs;
	var newRow = document.createElement('div');
	newRow.classList.add("row");
	
	var newCount = document.createElement('div');
	newCount.classList.add("col");
	newCount.classList.add("col-lg-2");
	newCount.innerHTML = '<table><tr><td>B:</td><td>'+balls+'</td></tr><tr><td>S:</td><td>'+strikes+'</td></tr><tr><td>O:</td><td>'+outs+'</td></tr></table>';
	newRow.appendChild(newCount);
	
	var newPlay = document.createElement('div');
	newPlay.classList.add("col");
	newPlay.classList.add("col-lg-8");
	newPlay.innerHTML = play_str + '<br />' + advance_str;
	newRow.appendChild(newPlay);
	
	var newRunners = document.createElement('div');
	newRunners.classList.add("col");
	newRunners.classList.add("col-lg-2");
	
	newRunners.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" version="1.2" baseProfile="tiny" viewBox="-.2 -.2 6.4 4.4" stroke-linecap="round" stroke-linejoin="round" stroke-width=".2" stroke="black" stroke-opacity="1" fill-opacity="1"><path onclick="" fill="'+firstFill+'" d="M 5 2 6 3 5 4 4 3 Z"/><path onclick="" fill="'+secondFill+'" d="M 3 0 4 1 3 2 2 1 Z"/><path onclick="" fill="'+thirdFill+'" d="M 1 2 2 3 1 4 0 3 Z"/></svg>';
	newRow.appendChild(newRunners);
	return newRow;
}

function createBatters(team){

	
    var columns = ['Name','PA','AB','H','BB','R','RBI','K'];
    	
	var table = d3.select('#'+team+'off-location').append('table').attr('class','stats_table')
		.attr('class',function () { if (team == 'home' ) {return "stats_table "+hometeam+"_primary"} else {return "stats_table "+awayteam+"_primary"}});
	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id',team+'offBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });
	
	var rows = tbody.selectAll('tr')
		.data(batterData[team])
		.enter()
	  .append('tr')
	  .attr('id',function(d,i) {return team+'Batter_'+i;})
	  .on('click', function(d,i) {clickedAwayBatter(i);});

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	.text(function (d) { return d });
	
}

function createPitchers(team){

	
    var columns = ['Name','IP','R','ER','H','BB','K','PC'];
    	
	var table = d3.select('#'+team+'pitcher-location').append('table')
		.attr('class',function () { if (team == 'home' ) {return "stats_table "+hometeam+"_secondary"} else {return "stats_table "+awayteam+"_secondary"}});
	var thead = table.append('thead');
	var tbody = table.append('tbody').attr('id',team+'pitcherBody');

	thead.append('tr')
	  .selectAll('th')
		.data(columns)
		.enter()
	  .append('th')
		.text(function (d) { return d });
	
	var rows = tbody.selectAll('tr')
		.data(pitcherData[team])
		.enter()
	  .append('tr')
	  .attr('id',function(d,i) {return team+'Pitcher_'+i;})
	  .on('click', function(d,i) {clickedAwayPitcher(i);});

	var cells = rows.selectAll('td')
		.data(function(row) {return row;})
	  .enter()
	.append('td')
	.text(function (d, i) { 
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

function clickedAwayBatter(i) {
	var ref = document.getElementById('awayBatter_'+i);
	var popup = document.getElementById('awayBatterInfo_'+i);
	popup.style.display = "inline-block";
	var popper = new Popper(ref,popup,{
		placement: 'right',
						
	});
}

function createGame(homeData,awayData,gameinfo) {

	document.getElementById('away-info').innerHTML = shiohteams[gameinfo.opp][year][0];
	document.getElementById('home-info').innerHTML = shiohteams[gameid.substring(0,3)][year][0];
		
		
	var maxgames = 5;
	var recentgames = [];
	var futuregames = [];
	var isrecent = true;
	var gameids = Object.keys(homeData);
	
    
    for (var i=0;i<gameids.length;i++) {
    	if (gameids[i] == gameid) {
    		isrecent = false;
    		homeData[gameid].id = gameid;
    		recentgames.push(homeData[gameid]);
    		if (recentgames.length > 2*maxgames + 1) {
    			recentgames = recentgames.slice(recentgames.length-2*maxgames-1, recentgames.length);
    		}
    	}
    	else if (isrecent) {
    		homeData[gameids[i]].id = gameids[i];
    		recentgames.push(homeData[gameids[i]]);
    	}
    	else if (futuregames.length < 2*maxgames+1) {
    		homeData[gameids[i]].id = gameids[i];
    		futuregames.push(homeData[gameids[i]]);
    	}
    	else {
    		break;
    	}
    }
    
    if (futuregames.length > maxgames && recentgames.length > maxgames+1) {
    	recentgames = recentgames.slice(recentgames.length-maxgames-1, recentgames.length);
    	futuregames = futuregames.slice(0, maxgames);
    }
    else if (futuregames.length > maxgames) {
    	var nfg = maxgames*2+1-recentgames.length;
    	futuregames = futuregames.slice(0, nfg);
    }
    else if (recentgames.length > maxgames+1) {
    	var nrg = maxgames*2+1-futuregames.length;
    	recentgames = recentgames.slice(recentgames.length-nrg, recentgames.length);
    }
    
    
	var homesched = d3.select('#right-sidebar').selectAll('div');

	homesched.data(recentgames.concat(futuregames))
		.enter()
	  .append('div')
		.text(function (d) { return createScheduledGame(d,0); })
		.attr('class', function (d) { if (d.id == gameid) {return 'currentgame'} else {return 'notme'} })
		.on('click', function(d,i) {clickedGame(d.id);})
		.append('div')
		.text(function (d) { return createScheduledGame(d,1); })
		.on('click', function(d,i) {clickedGame(d.id);})
	
	

	recentgames = [];
	futuregames = [];
	isrecent = true;
	gameids = Object.keys(awayData);
	
    
    for (var i=0;i<gameids.length;i++) {
    	if (gameids[i] == gameid) {
    		isrecent = false;
    		awayData[gameid].id = gameid;
    		recentgames.push(awayData[gameid]);
    		if (recentgames.length > 2*maxgames + 1) {
    			recentgames = recentgames.slice(recentgames.length-2*maxgames-1, recentgames.length);
    		}
    	}
    	else if (isrecent) {
    		awayData[gameids[i]].id = gameids[i];
    		recentgames.push(awayData[gameids[i]]);
    	}
    	else if (futuregames.length < 2*maxgames+1) {
    		awayData[gameids[i]].id = gameids[i];
    		futuregames.push(awayData[gameids[i]]);
    	}
    	else {
    		break;
    	}
    }
    
    if (futuregames.length > maxgames && recentgames.length > maxgames+1) {
    	recentgames = recentgames.slice(recentgames.length-maxgames-1, recentgames.length);
    	futuregames = futuregames.slice(0, maxgames);
    }
    else if (futuregames.length > maxgames) {
    	var nfg = maxgames*2+1-recentgames.length;
    	futuregames = futuregames.slice(0,nfg);
    }
    else if (recentgames.length > maxgames+1) {
    	var nrg = maxgames*2+1-futuregames.length;
    	recentgames = recentgames.slice(recentgames.length-nrg, recentgames.length);
    }
    
    
	var awaysched = d3.select('#left-sidebar').selectAll('div');

	awaysched.data(recentgames.concat(futuregames))
		.enter()
	  .append('div')
		.text(function (d) { return createScheduledGame(d,0); })
		.attr('class', function (d) { if (d.id == gameid) {return 'currentgame'} else {return 'notme'} })
		.on('click', function(d,i) {clickedGame(d.id);})
		.append('div')
		.text(function (d) { return createScheduledGame(d,1); })
		.on('click', function(d,i) {clickedGame(d.id);})

}

function createScheduledGame(game,nrow) {
	if (nrow == 0) {
		if (game.loc == 'H') { 
			return parseInt(game.id.substring(7,9)) + '/' + parseInt(game.id.substring(9,11)) + ' vs. '+game.opp + ' ' + game.result + ' ' + game.runs + '-' + game.allowed;
		}
		else if (game.loc == 'A') { 
			return parseInt(game.id.substring(7,9)) + '/' + parseInt(game.id.substring(9,11)) + ' @ '+game.opp + ' ' + game.result + ' ' + game.runs + '-' + game.allowed;
		}
	}
	else {
		return 'SP: '+shiohplayers[game.starter][0];
	}
	
}

function clickedGame(newid) {
	gameid = newid;
	hometeam = gameid.substring(0,3);
	year = gameid.substring(3,7);
	makeGame();
	//window.location.href = 'boxscore.html?id='+newid;

}








