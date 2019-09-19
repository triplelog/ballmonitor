
    	
		


function updateSlider(value1,value2=0) {
	addGame(value1,value2);
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
var dateRev = {};
var dateLen = Object.keys(fullSchedule).length;
for (var i=0;i<dateLen;i++) {
	dateList.push([Object.keys(fullSchedule)[i],0]);
	dateRev[Object.keys(fullSchedule)[i]] = i;
}

var weekdays = [
    "Sunday", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday",
    "Saturday"
];

var months = [
    "January", "February", "March",
    "April", "May", "June", "July",
    "August", "September", "October",
    "November", "December"
];

function datefromstr(rawstr) {
	str = rawstr.substring(4,6)+'/'+rawstr.substring(6,8)+'/'+rawstr.substring(0,4)+'';
	//console.log(str);
	var d = new Date(str);
	//console.log(d.getFullYear());
    return d;
}

function loadData(date= window.location.search.substring(6)) {

	year = date.substring(0,4);
	d3.json("data/years/"+year+"Data.json").then(function(data) {
		leagues = data['leagues'];
		divisions = data['divisions'];
		fullSchedule = data['games'];
		teams = data['teams'];
		dateList = [];
		dateRev = {};
		dateLen = Object.keys(fullSchedule).length;
		pvalues = [];
		chmonth = 7;
		
		var initialDate = dateLen;
		if (date.length > 4){
			initialDate = 0;
		}
		

		for (var i=0;i<dateLen;i++) {
			dateList.push([Object.keys(fullSchedule)[i],0]);
			hmonth = parseInt(Object.keys(fullSchedule)[i].substring(4,6))*2+parseInt(Math.min(parseInt(Object.keys(fullSchedule)[i].substring(6,8)),29)/16);
			if (hmonth > chmonth) {
				pvalues.push(i);
				chmonth = hmonth;
			}
			dateRev[Object.keys(fullSchedule)[i]] = i;
			if (date > Object.keys(fullSchedule)[i]) {
				initialDate = i;
			}
		}
		
		
		createStandings(year);
		updateSlider(initialDate);
		
		console.log(dateLen);
		if (2 == 2) {
		  var slider1 = document.getElementById('scheduleSlider');

			noUiSlider.create(slider1, {
				start: [0, initialDate],
				step: 1,
				behaviour: 'drag',
				connect: true,
				range: {
					'min': 0,
					'max': dateLen
				},
				pips: {
					mode: 'values',
					values: pvalues,
					density: 2,
					format: {
						// 'to' the formatted value. Receives a number.
						to: function (value) {
							return parseInt(dateList[value][0].substring(4,6))+'/'+dateList[value][0].substring(6,8);
						}
					}
				}
			});	 
			slider1.noUiSlider.on('update', function (values) { 
				updateSlider(parseInt(values[1]),parseInt(values[0]));
			});
		}
	  
	});
	
}

			   
function createStandings(year){

	
	teamData = {};
	nTeams = 0;
	
	
	for (var i=0; i < leagues.length; i++) {
		for (var ii=0;ii<divisions.length;ii++) {
			myData[leagues[i]+divisions[ii]]=[];
			for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {
				teamData[teams[leagues[i]][divisions[ii]][iii]] = {'wins':0,'losses':0,'runs':0,'allowed':0,'elo':1500,'sprs':0,'sprsos':0,'last10':[]};
				
				teamrow = [teams[leagues[i]][divisions[ii]][iii],0,0,0,'-',[],0,0,'0-0'];
				myData[leagues[i]+divisions[ii]].push(teamrow);
				
			}
			createDivision(leagues[i]+divisions[ii],leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
		}
	}
	
	

    
}


var bankroll = [1,0];
function addGame(dateIndex,dateStart=0){

	for (var di=dateStart;di<dateIndex;di++){
		if (dateList[di][1]<1) {
			var schedule = fullSchedule[dateList[di][0]];
	
			for (var i=0;i<schedule.length;i++){
			
				if (teamData[schedule[i]['hteam']]['losses']>9 && teamData[schedule[i]['hteam']]['wins']>9) {
					
					var expwph = 1.0/(1.0+Math.pow(teamData[schedule[i]['hteam']]['allowed']/teamData[schedule[i]['hteam']]['runs'],1.83));
					var expwpv = 1.0/(1.0+Math.pow(teamData[schedule[i]['vteam']]['allowed']/teamData[schedule[i]['vteam']]['runs'],1.83));
					var elodiffh = 400*Math.log(1/expwph-1)/Math.log(10)-400*Math.log(1/expwpv-1)/Math.log(10);
					var expHomeWin = 1.0/(1.0+ Math.pow(10.0,(elodiffh-24)/400.0));
					
					//var expHomeWin = 1.0/(1.0+ Math.pow(10.0,(teamData[schedule[i]['vteam']]['elo']-24-teamData[schedule[i]['hteam']]['elo'])/400.0));
				
					var actwph = teamData[schedule[i]['hteam']]['wins']/(teamData[schedule[i]['hteam']]['wins']+teamData[schedule[i]['hteam']]['losses']);
					var actwpv = teamData[schedule[i]['vteam']]['wins']/(teamData[schedule[i]['vteam']]['wins']+teamData[schedule[i]['vteam']]['losses']);
					var elodiffha = 400*Math.log(1/actwph-1)/Math.log(10)-400*Math.log(1/actwpv-1)/Math.log(10);
					var actHomeWin = 1.0/(1.0+ Math.pow(10.0,(elodiffha)/400.0));
					
			
					var sprsmh = teamData[schedule[i]['hteam']]['sprs'];//*4/5+teamData[schedule[i]['hteam']]['sprsos']/5;
					var sprsmv = teamData[schedule[i]['vteam']]['sprs'];//*4/5+teamData[schedule[i]['vteam']]['sprsos']/5;
					expwphh = 1.0/(1.0+Math.pow(10.0,(sprsmv/(teamData[schedule[i]['vteam']]['losses']+teamData[schedule[i]['vteam']]['wins'])-24-sprsmh/(teamData[schedule[i]['hteam']]['losses']+teamData[schedule[i]['hteam']]['wins']))/400));
					
					//expwphh = expHomeWin;
					//expwphh = .5;
					
					if (schedule[i]['hruns']>schedule[i]['vruns']) {
						bankroll[0] += Math.pow(expwphh-1,2.0);
					}
					else {
						bankroll[0] += Math.pow(expwphh,2.0);
					}
					bankroll[1] += 1;
					if (2 == 3) {
						if (expwphh > actHomeWin + .01){
							var b = 1/actHomeWin-1;
							var fb = .1*(expwphh*(b+1)-1)/b;
							//console.log(b,fb,bankroll[0],expwphh, expHomeWin);
							if (schedule[i]['hruns']>schedule[i]['vruns']) {
								bankroll[0] += fb*bankroll[0]*b;//expwphh - expHomeWin;
							}
							else {
								bankroll[0] -= fb*bankroll[0];//expwphh - expHomeWin;
							}
						}
						else if (expwphh + .01 < actHomeWin){
							var b = 1/(1-actHomeWin)-1;
							var fb = .1*((1-expwphh)*(b+1)-1)/b;
							if (schedule[i]['hruns']>schedule[i]['vruns']) {
								bankroll[0] -= fb*bankroll[0];//expwphh - expHomeWin;
							}
							else {
								bankroll[0] += fb*bankroll[0]*b;//expwphh - expHomeWin;
							}
						}
					}
				}

				runs1 = schedule[i]['vruns'];
				runs2 = schedule[i]['hruns'];
				var k = 5.0;
				var probHomeWin = 1.0/(1.0+ Math.pow(10.0,(teamData[schedule[i]['vteam']]['elo']-teamData[schedule[i]['hteam']]['elo'])/400.0));
				var sprsv = 1.0/(1.0+Math.pow((runs2+1.0)/(runs1+1.0),1.4));
				var sprsh = 1.0/(1.0+Math.pow((runs1+1.0)/(runs2+1.0),1.4));
				
				teamData[schedule[i]['hteam']]['sprs'] += -400*Math.log(1/sprsh-1)/Math.log(10)-12;
				teamData[schedule[i]['vteam']]['sprs'] += -400*Math.log(1/sprsv-1)/Math.log(10)+12;
				
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
				
				if (teamData[schedule[i]['vteam']]['wins']+teamData[schedule[i]['vteam']]['losses'] > 0 && teamData[schedule[i]['hteam']]['wins']+teamData[schedule[i]['hteam']]['losses'] > 0) {
					teamData[schedule[i]['hteam']]['sprsos'] += teamData[schedule[i]['vteam']]['sprs']/(teamData[schedule[i]['vteam']]['wins']+teamData[schedule[i]['vteam']]['losses']);
					teamData[schedule[i]['vteam']]['sprsos'] += teamData[schedule[i]['hteam']]['sprs']/(teamData[schedule[i]['hteam']]['wins']+teamData[schedule[i]['hteam']]['losses']);
				}
				
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
				
				var sprsv = 1.0/(1.0+Math.pow((runs2+1.0)/(runs1+1.0),1.8));
				var sprsh = 1.0/(1.0+Math.pow((runs1+1.0)/(runs2+1.0),1.8));
				
				teamData[schedule[i]['hteam']]['sprs'] -= -400*Math.log(1/sprsh-1)/Math.log(10);
				teamData[schedule[i]['vteam']]['sprs'] -= -400*Math.log(1/sprsv-1)/Math.log(10);
				
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
				
				teamData[schedule[i]['hteam']]['sprsos'] -= teamData[schedule[i]['vteam']]['sprs']/(teamData[schedule[i]['vteam']]['wins']+teamData[schedule[i]['vteam']]['losses']);
				teamData[schedule[i]['vteam']]['sprsos'] -= teamData[schedule[i]['hteam']]['sprs']/(teamData[schedule[i]['hteam']]['wins']+teamData[schedule[i]['hteam']]['losses']);
				
			}
			
			dateList[di][1]=0;
		}
	}
	for (var di=0;di<dateStart;di++){
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
	console.log(bankroll, bankroll[0]/(bankroll[1]), 1 - (bankroll[0]/(bankroll[1]))/.250455, 1 - (bankroll[0]/(bankroll[1]))/.25 );
	updateStandings();
	
}

function updateStandings() {
	myData = {};
	for (var i=0; i < leagues.length; i++) {
		for (var ii=0;ii<divisions.length;ii++) {
			myData[leagues[i]+divisions[ii]]=[];
			for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {

				teamrow = [teams[leagues[i]][divisions[ii]][iii],teamData[teams[leagues[i]][divisions[ii]][iii]]['wins'],teamData[teams[leagues[i]][divisions[ii]][iii]]['losses'],0,'-',teamData[teams[leagues[i]][divisions[ii]][iii]]['last10'],teamData[teams[leagues[i]][divisions[ii]][iii]]['runs'],teamData[teams[leagues[i]][divisions[ii]][iii]]['allowed'],'0-0'];
				if (teamrow[1]+teamrow[2] > 0) {
					teamrow[3] = (teamrow[1]/(teamrow[1]+teamrow[2])).toFixed(3);
				}
				if (teamrow[5].length > 10) {
					teamrow[5] = teamData[teams[leagues[i]][divisions[ii]][iii]]['last10'].slice(teamData[teams[leagues[i]][divisions[ii]][iii]]['last10'].length-10,teamData[teams[leagues[i]][divisions[ii]][iii]]['last10'].length);
				}
				if (teamrow[6] > 0) {
					
					var expwp = 1.0/(1.0+Math.pow(teamrow[7]/teamrow[6],1.83));
					var expwins = Math.round(expwp * (teamrow[1]+teamrow[2])).toFixed(0);
					var explosses = (teamrow[1]+teamrow[2] - expwins).toFixed(0);
					teamrow[8] = expwins + '-' + explosses;
					
					var sprsm = teamData[teams[leagues[i]][divisions[ii]][iii]]['sprs'];//*2/3+teamData[teams[leagues[i]][divisions[ii]][iii]]['sprsos']/3;
					expwp = 1.0/(1.0+Math.pow(10.0,(0-sprsm/(teamrow[1]+teamrow[2]))/400));
					expwins = Math.round(expwp * (teamrow[1]+teamrow[2])).toFixed(0);
					explosses = (teamrow[1]+teamrow[2] - expwins).toFixed(0);
					//teamrow[9] = expwins + '-' + explosses;
				}
				else {
					var expwp = 0.0;
					teamrow[8] =  '0-' + teamrow[2];
					//teamrow[9] =  '0-' + teamrow[2];
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
			updateDivision(leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
		}
	}
	
	
}


function createDivision(divID,divName,divData) {
	var columns = [divName,'W','L','PCT','GB','Last 10','RS','RA','ExpW-L'];
    
	var leagueDiv = d3.select('#'+divID.substring(0,2))
						.append('div')
						.attr('classList','col col-lg-12')
						.attr('id', divID);
						
	var table = d3.select('#'+divID).append('table')
					.attr('class','stats_table stats_table_sm table_fullw');
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
	  .append('tr');

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
		.attr('style',function (d,i) { 
			if (isNaN(parseInt(d[4]))) {
				return 'border-top: 0px solid transparent; border-bottom: 0px solid transparent;';
			}
			else if (isNaN(parseInt(divData[i-1][4]))){
				newgb = parseInt(d[4]);
				return 'border-top: '+newgb+'px solid transparent; border-bottom: 0px solid transparent;';
			}
			else {
				newgb = parseInt(d[4]) - parseInt(divData[i-1][4]);
				return 'border-top: '+newgb+'px solid transparent; border-bottom: 0px solid transparent;';
			}
		  });

	  
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






