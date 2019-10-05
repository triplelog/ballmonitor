class SeasonStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	
	
	let template = document.getElementById('stats');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
	this.displayStats = [];
	this.leaderColumns = [];
  	
  	var ncbutton = this.shadowRoot.querySelector('#newcol');
  	this.tippyColumn = tippy(ncbutton, {
	  content: 'Name:<input type="text" id="colName"/><br />Formula:<input type="text" id="colFormula"/><br />Format:<input type="text" id="colFormat" /><br /><button id="tippyColumnButton">Submit</button><button>Cancel</button>',
	  interactive: true,
	  trigger: "click",
	  hideOnClick: false,
	  placement: "bottom",
	  onMount(instance) {
		console.log(_this.shadowRoot.querySelector('#tippyColumnButton'));
		_this.shadowRoot.querySelector('#tippyColumnButton').addEventListener("click", e => {_this.newcolumn(e);});
	  },
	  
	});
  	
  	
  	this.chgsrc();
  	
  	
	
	
  }
  
  newcolumn(e) {
  	var tippyNode = e.target.parentNode;
  	console.log(tippyNode.querySelector('#colName').value);
  	console.log(tippyNode.querySelector('#colFormula').value);
  	console.log(tippyNode.querySelector('#colFormat').value);
  	this.addColumn(tippyNode.querySelector('#colFormula').value,tippyNode.querySelector('#colName').value,"=3");
    this.stats(0);
  	this.stats(this.currentYear);
  	this.tippyColumn.hide();
  }
  
  buttonAdded(){
  	var button = this.shadowRoot.querySelector('#chgLeaderColumns');
  	button.addEventListener("click", e => {this.chgLeaderColumns();});
  }
  
  chgLeaderColumns() {
  	var allChecks = this.shadowRoot.querySelectorAll('input[type="checkbox"]');
  	this.leaderColumns = [];
  	for (var i=0;i<allChecks.length;i++){
  		if (allChecks[i].checked && allChecks[i].id){
			var splitID = allChecks[i].id.split('_');
			if (splitID[0] == 'stat'){
				var checkID = parseInt(splitID[1]);
				this.leaderColumns.push(checkID);
			}
  		}
  	}
  }
  
  chgsrc() {
  	var _this = this;
    this.playerid = this.getAttribute('src');
    if (this.playerid == null) {return 0;}
    
  	var url = 'player/'+this.playerid+'.csv';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();

    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            _this.playerStats = Papa.parse(jsonFile.responseText).data;
            _this.currentYear = parseInt(_this.playerStats[1][0].substring(0,4));
            _this.addColumn("H","H","0");
            _this.addColumn("AB","AB","0");
            _this.addColumn("H/AB","AVG","=3");
            _this.addColumn("AVG+1","AAA","=3");
            _this.sortInfo = [[0,-1,'AVG'],[0,1,'']];
            _this.stats(0);
  			_this.stats(_this.currentYear);
  		}
     }
    
  }
  
  addColumn(cformula,cname,cdisplay) {
  	for (var i=0;i<this.displayStats.length;i++){
  		if (this.displayStats[i][1] == cname){
  			return 0;
  		}
  	}
  	this.colInfo = {};
  	for (var i = 0;i<this.playerStats[0].length;i++){
  		this.colInfo[i] = this.playerStats[0][i];
	}
  	console.log(postfixify(cformula,this.colInfo));
  	this.displayStats.push([postfixify(cformula,this.colInfo),cname,cformula,cdisplay]);
  	if (postfixify(cformula,this.colInfo).split('_').length>1){
  		this.playerStats[0].push(cname);
  	}
  	
  }
  sortBy(e,x) {
  	if (this.sortInfo[x][2] == e.target.textContent){
  		this.sortInfo[x][1] = -1*this.sortInfo[x][1];
  	}
  	else {
  		this.sortInfo[x][1] = -1;
  	}
  	this.sortInfo[x][2] = e.target.textContent;
  	this.stats(0);
  	this.stats(this.currentYear);
  }
  stats(seasonYear=0) {
    var statarray = this.playerStats;
    
  	var offboxa = this.shadowRoot.querySelector('#career-location');
  	
  	if (seasonYear != 0){
		this.currentYear = seasonYear;
		offboxa = this.shadowRoot.querySelector('#season-location');
		this.sortInfo[1][0] = 0;
  	}
  	else {
  		this.sortInfo[0][0] = 0;
  	}
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	var statobjects = [];
  	
  	
  	var th = document.createElement('th');
  	if (seasonYear != 0){
		th.textContent = 'Month';
		th.addEventListener("click", e => {this.sortBy(e,1);});
	}
	else {
		th.textContent = 'Year';
		th.addEventListener("click", e => {this.sortBy(e,0);});
	}
	theada.appendChild(th);
  	this.displayStats.forEach(x => {
  		th = document.createElement('th');
		th.textContent = x[1];
		if (seasonYear == 0) {
			th.addEventListener("click", e => {this.sortBy(e,0);});
		}
		else {
			th.addEventListener("click", e => {this.sortBy(e,1);});
		}
		theada.appendChild(th);
		var cols = x[0].split('@')[0].split('_');
		for (var ii=0;ii<cols.length;ii++){
			var ncol = parseInt(cols[ii].substring(1,));
			for (var iii=0;iii<statobjects.length+1;iii++) {
				if (iii == statobjects.length){
					statobjects.push(ncol);
					break;
				}
				else if (ncol == statobjects[iii]) {
					break;
				}
			}
			
		}
	});
	
	var currentOrder = 0;
	var currentClass = 1;
	
	var years = {total:{}};
	for (var ii=0;ii<statobjects.length;ii++){
		years.total[statobjects[ii]] =  0;
	}
	for (var i=1;i<statarray.length;i++){
		if (statarray[i].length < 10){continue;}
		if (seasonYear != 0 && parseInt(statarray[i][0].substring(0,4)) != parseInt(seasonYear)){continue;}
		var year = statarray[i][0].substring(0,4);
		if (seasonYear != 0){
			year = statarray[i][0].substring(4,6);
		}
		if (years.hasOwnProperty(year)){
			
		}
		else {
			years[year] = {};
			for (var ii=0;ii<statobjects.length;ii++){
				years[year][statobjects[ii]] =  0;
			}
		}
		
		for (var ii=0;ii<statobjects.length;ii++){
			if (parseInt(statarray[i][27])==1 && statobjects[ii] < statarray[i].length) {
				years[year][statobjects[ii]] += parseInt(statarray[i][statobjects[ii]]);
				years.total[statobjects[ii]] += parseInt(statarray[i][statobjects[ii]]);
			}
		}

	}
	var orderedData = [];
	
	for(var year in years){
		if (year == 'total'){continue;}
		var oneyear = [[parseInt(year),year]];
		if (seasonYear != 0){oneyear[0][1] = monthnames[parseInt(year)];}
		var i = 1;
		this.displayStats.forEach(x => {
			var nc = parseInt(postfixify(x[1],this.colInfo).split('@')[0].substring(1,));
			var ncd = solvepostfixjs(years[year],x[0]);
			years[year][nc] = ncd;
			if (x[3][0] == '='){
				oneyear.push([ncd,roundFixed(ncd,parseInt(x[3].substring(1)),true)]);
			}
			else {
				oneyear.push([ncd,roundFixed(ncd,parseInt(x[3]),false)]);
			}
			if (seasonYear == 0 && x[1] == this.sortInfo[0][2]){this.sortInfo[0][0] = i;}
			else if (seasonYear != 0 && x[1] == this.sortInfo[1][2]){this.sortInfo[1][0] = i;}
			i++;
		});
		orderedData.push(oneyear);
	}
	if (seasonYear == 0) {
		if (this.sortInfo[0][1] == -1){orderedData.sort((a, b) => b[this.sortInfo[0][0]][0] - a[this.sortInfo[0][0]][0]);}
		else {orderedData.sort((a, b) => a[this.sortInfo[0][0]][0] - b[this.sortInfo[0][0]][0]);}
	}
	else {
		if (this.sortInfo[1][1] == -1){orderedData.sort((a, b) => b[this.sortInfo[1][0]][0] - a[this.sortInfo[1][0]][0]);}
		else {orderedData.sort((a, b) => a[this.sortInfo[1][0]][0] - b[this.sortInfo[1][0]][0]);}
	}
	for(var i=0;i<orderedData.length;i++){
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		for (var ii=0;ii<orderedData[i].length;ii++){
			var td = document.createElement('td');
			td.textContent =  orderedData[i][ii][1];
			tr.appendChild(td);
		}
		tbodya.appendChild(tr);
	}
	var tr = document.createElement('tr');
	tr.classList.add("tr1");
	var td = document.createElement('td');
	td.textContent = 'Total';
	tr.appendChild(td);
	var ii = 0;
	this.displayStats.forEach(x => {
		td = document.createElement('td');
		var nc = parseInt(postfixify(x[1],this.colInfo).split('@')[0].substring(1,));
		var ncd = solvepostfixjs(years.total,x[0])
		td.textContent = roundFixed(ncd,3,false);
		years.total[nc] = ncd;
		tr.appendChild(td);
		ii++;
	});
	
	tbodya.appendChild(tr);
  }
  
  
	
  
}

customElements.define('season-stats', SeasonStats);

class SeasonStandings extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	
	
	let template = document.getElementById('standings');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
  	
  	//this.chgsrc();
  	this.fullSchedule = {};
	this.dateList = [];
	this.teamData = {};

  	this.loadData(2018);
  	//this.addGame(2);
  	//this.createDivision('NLEAST','NL East',[[0,0,0,0,0,0,0,0,0]]);
  	multirange(this.shadowRoot.querySelector('#slider'));
  	
  	this.shadowRoot.querySelectorAll('#slider')[0].addEventListener("input",e => {this.updateSlider();});
  	this.shadowRoot.querySelectorAll('#slider')[1].addEventListener("input",e => {this.updateSlider();});
  	
  	this.tabdnSeason = document.querySelector('tabdn-season');
  	
  	
	
	
  }
  
  updateSlider() {
  	var lowerV = parseInt(this.shadowRoot.querySelector('#slider').valueLow);
  	var upperV = parseInt(this.shadowRoot.querySelector('#slider').valueHigh);
  	this.addGame(upperV,lowerV);
  	this.tabdnSeason.filterLeaders(upperV);
  }
  loadData(year) {
  	var _this = this;
  	var url = 'seasons/2018Data.json';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();

    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            var data = JSON.parse(jsonFile.responseText);
            _this.leagues = data['leagues'];
			_this.divisions = data['divisions'];
			var leagues = _this.leagues;
			var divisions = _this.divisions;
			_this.fullSchedule = data['games'];
			_this.teams = data['teams'];
			var teams = _this.teams;
			_this.dateList = [];
			var dateRev = {};
			_this.dateLen = Object.keys(_this.fullSchedule).length;
			/*
			pvalues = [];
			chmonth = 7;
			*/
			_this.initialDate = _this.dateLen;
			/*
			if (date.length > 4){
				initialDate = 0;
			}
			*/

			for (var i=0;i<_this.dateLen;i++) {
				_this.dateList.push([Object.keys(_this.fullSchedule)[i],0]);
				/*
				hmonth = parseInt(Object.keys(_this.fullSchedule)[i].substring(4,6))*2+parseInt(Math.min(parseInt(Object.keys(_this.fullSchedule)[i].substring(6,8)),29)/16);
				if (hmonth > chmonth) {
					pvalues.push(i);
					chmonth = hmonth;
				}
				dateRev[Object.keys(_this.fullSchedule)[i]] = i;
				if (date > Object.keys(_this.fullSchedule)[i]) {
					initialDate = i;
				}
				*/
			}
			
			_this.teamData = {};
			var myData = {};
	
	
			for (var i=0; i < leagues.length; i++) {
				var leagueDiv = _this.shadowRoot.querySelector('#'+leagues[i]);
				leagueDiv.innerHTML = '';
				for (var ii=0;ii<divisions.length;ii++) {
					myData[leagues[i]+divisions[ii]]=[];
					for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {
						_this.teamData[teams[leagues[i]][divisions[ii]][iii]] = {'wins':0,'losses':0,'runs':0,'allowed':0,'elo':1500,'sprs':0,'sprsos':0,'last10':[]};
				
						var teamrow = [teams[leagues[i]][divisions[ii]][iii],0,0,0,'-',[],0,0,'0-0'];
						myData[leagues[i]+divisions[ii]].push(teamrow);
				
					}
					
					var divDiv = document.createElement('div');
					divDiv.id = leagues[i]+divisions[ii];
					leagueDiv.appendChild(divDiv);
					_this.createDivision(leagues[i]+divisions[ii],leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
				}
			}
			_this.addGame(100);
  		}
     }
     /*
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
		

	  
		});
		*/
	
	}
  
  createDivision(divID,divName,divData) {
		var columns = [divName,'W','L','PCT','GB','Last 10','RS','RA','ExpW-L'];
	
		var divDiv = this.shadowRoot.querySelector('#'+divID);
		divDiv.innerHTML = '';
						
		var table = document.createElement('table');
		var thead = document.createElement('thead');
		var tbody = document.createElement('tbody');
		tbody.id = divID+'Body';
		var tr = document.createElement('tr');
		for (var i=0;i<columns.length;i++){
			var th = document.createElement('th');
			th.textContent = columns[i];
			tr.appendChild(th);
		}
		thead.appendChild(tr);
		
		for (var ii=0;ii<divData.length;ii++){
			tr = document.createElement('tr');
			for (var i=0;i<divData[ii].length;i++){
				var td = document.createElement('td');
				td.textContent = divData[ii][i];
				tr.appendChild(td);
			}
			tbody.appendChild(tr);
		}
		
		table.appendChild(thead);
		table.appendChild(tbody);
		divDiv.appendChild(table);

	}
	
  updateStandings() {
		var myData = {};
		var leagues = this.leagues;
		var divisions = this.divisions;
		var teams = this.teams;
		var teamData = this.teamData;
		for (var i=0; i < leagues.length; i++) {
			for (var ii=0;ii<divisions.length;ii++) {
				myData[leagues[i]+divisions[ii]]=[];
				for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {

					var teamrow = [teams[leagues[i]][divisions[ii]][iii],teamData[teams[leagues[i]][divisions[ii]][iii]]['wins'],teamData[teams[leagues[i]][divisions[ii]][iii]]['losses'],0,'-',teamData[teams[leagues[i]][divisions[ii]][iii]]['last10'],teamData[teams[leagues[i]][divisions[ii]][iii]]['runs'],teamData[teams[leagues[i]][divisions[ii]][iii]]['allowed'],'0-0'];
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
				var maxWL = myData[leagues[i]+divisions[ii]][0][1]-myData[leagues[i]+divisions[ii]][0][2];
				for (var iii=0;iii<teams[leagues[i]][divisions[ii]].length;iii++) {
					if (myData[leagues[i]+divisions[ii]][iii][1]-myData[leagues[i]+divisions[ii]][iii][2] >= maxWL) {
						myData[leagues[i]+divisions[ii]][iii][4] = '-';
					}
					else {
						myData[leagues[i]+divisions[ii]][iii][4] = ((maxWL - (myData[leagues[i]+divisions[ii]][iii][1]-myData[leagues[i]+divisions[ii]][iii][2]))/2).toFixed(1);
					}
				}
				this.createDivision(leagues[i]+divisions[ii],leagues[i]+divisions[ii],myData[leagues[i]+divisions[ii]]);
			}
		}
	
	
	}
  
  chgsrc() {
  	var _this = this;
    this.playerid = this.getAttribute('src');
    if (this.playerid == null) {return 0;}
    
  	var url = 'player/'+this.playerid+'.csv';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();

    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            _this.playerStats = Papa.parse(jsonFile.responseText).data;
            
  		}
     }
    
  }
  
  
  addGame(dateIndex,dateStart=0){
		var dateList = this.dateList;
		var fullSchedule = this.fullSchedule;
		var teamData = this.teamData;
		for (var di=dateStart;di<dateIndex;di++){
			if (dateList[di][1]<1) {
				var schedule = fullSchedule[dateList[di][0]];
	
				for (var i=0;i<schedule.length;i++){

					var runs1 = schedule[i]['vruns'];
					var runs2 = schedule[i]['hruns'];
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
		for (var di=dateIndex;di<this.dateLen;di++){
			if (dateList[di][1]==1) {
				var schedule = fullSchedule[dateList[di][0]];
	
				for (var i=0;i<schedule.length;i++){

					var runs1 = schedule[i]['vruns'];
					var runs2 = schedule[i]['hruns'];
				
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

					var runs1 = schedule[i]['vruns'];
					var runs2 = schedule[i]['hruns'];
				
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
	
	this.updateStandings();
	}
  
  
	
  
}

customElements.define('season-standings', SeasonStandings);

class TabDNSeason extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
		this.createTable();
    	//this.addPaginate();
    	//this.addButtons();
    	
    	this.ws.onopen = function(){
			var jsonmessage = {'command':'create','src':_this.getAttribute('src')};
			_this.ws.send(JSON.stringify(jsonmessage));
			if (_this.getAttribute('autoload')){
				if (_this.usecache){
					_this.usecache = false;
					var jsonmessage = {'command':'load'};
					_this.ws.send(JSON.stringify(jsonmessage));
					jsonmessage = { command: 'filter', formula: 'c28_/17532_c28_12/1/2018@##>##<&' };
					_this.ws.send(JSON.stringify(jsonmessage));
					jsonmessage = {'command':'multisort', 'columns':[7,8,9]};
					_this.ws.send(JSON.stringify(jsonmessage));
				}
			}
		};
	}
	
	
	filterLeaders(endDate){
		endDate += 17652;
		var jsonmessage = { command: 'filter', formula: 'c28_/17652_c28_/'+endDate+'@##>##<&' };
		this.ws.send(JSON.stringify(jsonmessage));
		console.log(this.columnLeaders);
		jsonmessage = {'command':'multisort', 'columns':this.columnLeaders};
		this.ws.send(JSON.stringify(jsonmessage));
	}
	
	 addData(retmess,type='single') {
	 	
		var players = document.querySelectorAll('season-stats');
		var i = 0;
		if (type == 'multi'){
			console.log(retmess);
			var leaderDiv = players[0].shadowRoot.querySelector('#statLeaders');
			leaderDiv.innerHTML = '';
			for (var stat in retmess) {
				var table = document.createElement('table');
				var tr = document.createElement('tr');
				var th = document.createElement('th');
				th.setAttribute('colspan','2');
				th.textContent = stat;
				tr.appendChild(th);
				table.appendChild(tr);
				for (i=0;i<retmess[stat].length;i++){
					tr = document.createElement('tr');
					
					var td = document.createElement('td');
					td.textContent = retmess[stat][i][0];
					tr.appendChild(td);
					
					td = document.createElement('td');
					td.textContent = retmess[stat][i][1];
					tr.appendChild(td);
					
					table.appendChild(tr);
				}
				
				leaderDiv.appendChild(table);
			}
			

		}
		else {
			for (var ii=0;ii*2 + 1<retmess[0].length;ii++) {
				this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
			}
			var editCols = players[0].shadowRoot.querySelector('#statsEdit');
			editCols.innerHTML = '';
			for (var col in this.colInfo){
				var input = document.createElement('input');
				input.type = "checkbox";
				input.id = "stat_"+col;
				var label = document.createElement('label');
				label.setAttribute('for',"stat_"+col);
				label.textContent = this.colInfo[col];
				editCols.appendChild(input);
				editCols.appendChild(label);
			}
			var button = document.createElement('button');
			button.textContent = 'Submit';
			button.id = "chgLeaderColumns";
			
			editCols.appendChild(button);
			players[0].buttonAdded();
		}
		
		/*
		for (var ii=1;ii<2;ii++) {
			if (players.length > ii - 1){
				//boxes[ii-1].setAttribute("src",retmess[ii][1]);
				players[ii-1].setAttribute("src","aaroh101battingstats");
				players[ii-1].chgsrc();
			}
			else {
				var player = document.createElement('player-stats');
				//box.setAttribute("src",retmess[ii][1]);
				player.setAttribute("src","aaroh101battingstats");
				player.chgsrc();
				this.parentNode.appendChild(player);
			}
		}
		*/

    }
	
	
}

customElements.define('tabdn-season', TabDNSeason);

