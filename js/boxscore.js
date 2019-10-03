class BoxScore extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	let template = document.getElementById('boxscore');
    let templateContent = template.content;
    
    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
    this.dataFiles = {prev:{id:null},current:{id:null},next:{id:null}};
    this.chgsrc();
	
    
    

	

  }
  
  chgsrc() {
  	var _this = this;
  	//Need deep copies of these objects!
  	if (this.getAttribute('src') == null) {return 0;}
  	else {
  		this.dataFiles.prev.id = this.getAttribute('psrc');
  		this.dataFiles.current.id = this.getAttribute('src');
  		this.dataFiles.next.id = this.getAttribute('nsrc');
  	}
    
    this.style.opacity = 0;
    if (!dataBoxes.hasOwnProperty(this.dataFiles.current.id)){
    	dataBoxes[this.dataFiles.current.id]={};
    }
    if (!dataBoxes[this.dataFiles.current.id].hasOwnProperty('batters')){
    	this.loadbatters(this.dataFiles.current.id,true);
    }
    else{_this.offbox(dataBoxes[this.dataFiles.current.id].batters);}
    if (!dataBoxes[this.dataFiles.current.id].hasOwnProperty('pitchers')){
    	this.loadpitchers(this.dataFiles.current.id,true);
    }
    else{_this.pitchbox(dataBoxes[this.dataFiles.current.id].pitchers);}
    if (!dataBoxes[this.dataFiles.current.id].hasOwnProperty('plays') || !dataBoxes[this.dataFiles.current.id].hasOwnProperty('info')){
    	this.loadinfo(this.dataFiles.current.id,true);
    }
    else{
    	var awayteam = "Away";
		var hometeam = "Home";
		var gameinfo = dataBoxes[this.dataFiles.current.id].info;
		for (var i=0;i<gameinfo.length;i++){
			if (gameinfo[i][1] == 'visteam') {awayteam = gameinfo[i][2];}
			else if (gameinfo[i][1] == 'hometeam') {hometeam = gameinfo[i][2];}
		}
  		this.fillscore(dataBoxes[this.dataFiles.current.id].plays,awayteam,hometeam);
  	}
    this.style.opacity = 1;
    
    
    if (!dataBoxes.hasOwnProperty(this.dataFiles.next.id)){
    	dataBoxes[this.dataFiles.next.id]={};
    	this.loadbatters(this.dataFiles.next.id,false);
    	this.loadpitchers(this.dataFiles.next.id,false);
    	this.loadinfo(this.dataFiles.next.id,false);
    }
    if (!dataBoxes.hasOwnProperty(this.dataFiles.prev.id)){
    	dataBoxes[this.dataFiles.prev.id]={};
    	this.loadbatters(this.dataFiles.prev.id,false);
    	this.loadpitchers(this.dataFiles.prev.id,false);
    	this.loadinfo(this.dataFiles.prev.id,false);
    }     
     
	
  }
  
  loadbatters(gameid,todisplay=false){
  	var _this = this;
  	var url = 'box/2000/2000'+gameid.substring(0,3)+'/'+gameid+'batterbox.csv';
	var jsonFile2 = new XMLHttpRequest();
	jsonFile2.open("GET",url,true);
	jsonFile2.send();

	jsonFile2.onloadend = function() {
		if(jsonFile2.status == 404) {
			_this.style.opacity = 0;
		}
		else if (jsonFile2.status == 200) {
			dataBoxes[gameid].batters = Papa.parse(jsonFile2.responseText).data;
			if (todisplay){
				_this.offbox(dataBoxes[gameid].batters);
			}
		}
	 }
  }
  loadpitchers(gameid,todisplay=false){
  	var _this = this;
  	var url = 'box/2000/2000'+gameid.substring(0,3)+'/'+gameid+'pitcherbox.csv';
	var jsonFile1 = new XMLHttpRequest();
	jsonFile1.open("GET",url,true);
	jsonFile1.send();

	jsonFile1.onloadend = function() {
		if(jsonFile1.status == 404) {
			_this.style.opacity = 0;
		}
		else if (jsonFile1.status == 200) {
			dataBoxes[gameid].pitchers = Papa.parse(jsonFile1.responseText).data;
			if (todisplay){
				_this.pitchbox(dataBoxes[gameid].pitchers);
			}
		}
	 }
  }
  loadinfo(gameid,todisplay=false){
  	var _this = this;
  	var url = 'box/2000/2000'+gameid.substring(0,3)+'/'+gameid+'.txt';
	var jsonFile3 = new XMLHttpRequest();
	jsonFile3.open("GET",url,true);
	jsonFile3.send();

	jsonFile3.onloadend = function() {
		if(jsonFile3.status == 404) {
			_this.style.opacity = 0;
		}
		else if (jsonFile3.status == 200) {
			dataBoxes[gameid].info = Papa.parse(jsonFile3.responseText).data;
			_this.linescore(gameid,dataBoxes[gameid].info,todisplay);
		}
	 }
  }
  loadplays(gameid,awayteam,hometeam,todisplay=false){
  	var _this = this;
  	var url = 'box/2000/2000'+gameid.substring(0,3)+'/'+gameid+'plays.csv';
	var jsonFile4 = new XMLHttpRequest();
	jsonFile4.open("GET",url,true);
	jsonFile4.send();

	jsonFile4.onreadystatechange = function() {
		if (jsonFile4.readyState== 4 && jsonFile4.status == 200) {
			dataBoxes[gameid].plays = Papa.parse(jsonFile4.responseText).data;
			if (todisplay){
				_this.fillscore(dataBoxes[gameid].plays,awayteam,hometeam);
			}
		}
	 }
  }
  linescore(gameid,gameinfo,todisplay=false) {
  	var awayteam = "Away";
	var hometeam = "Home";
  	for (var i=0;i<gameinfo.length;i++){
  		if (gameinfo[i][1] == 'visteam') {awayteam = gameinfo[i][2];}
  		else if (gameinfo[i][1] == 'hometeam') {hometeam = gameinfo[i][2];}
  	}
  	
  	this.loadplays(gameid,awayteam,hometeam,todisplay);

  }
  
  fillscore(linescoreRaw,awayteam,hometeam) {
  	var _this = this;
	var linescore = _this.shadowRoot.querySelector('#linescore-location');
	var thead = linescore.querySelector('thead').querySelector('tr');
	var row1 = linescore.querySelector('tbody').querySelectorAll('tr')[0];
	var row2 = linescore.querySelector('tbody').querySelectorAll('tr')[1];
	thead.innerHTML = '';
	row1.innerHTML = '';
	row2.innerHTML = '';


	var pbpLength = linescoreRaw.length;
	  var linescorearray = [[awayteam],[hometeam]];
	  var playarray = [[],[]];
	  var currentTeam = '1';
	  var halfRuns = 0;
	  var halfIndex = -1;
	  var currentouts = 0;
	  var totals = [[0,0,0],[0,0,0]]
	  _this.shadowRoot.querySelector('#away-extra').innerHTML = '';
	  _this.shadowRoot.querySelector('#home-extra').innerHTML = '';
	  for (var i=1;i<pbpLength;i++) {
		  if (linescoreRaw[i][15] == '0' && currentTeam == '1') {
			halfRuns = 0;
			halfIndex += 1;
			linescorearray[0].push(0);
			playarray[0].push([linescoreRaw[i][13]]);
			currentouts = 0;
		  }
		  else if (linescoreRaw[i][15] == '1' && currentTeam == '0') {
			halfRuns = 0;
			halfIndex += 1;
			linescorearray[1].push(0);
			playarray[1].push([linescoreRaw[i][13]]);
			currentouts = 0;
		  }
		  else {
		  	playarray[halfIndex%2][parseInt(halfIndex/2)].push(linescoreRaw[i][13]);
		  }
		  
		  if (parseInt(linescoreRaw[i][12]) > 0) {
			halfRuns += parseInt(linescoreRaw[i][12]);
			linescorearray[halfIndex%2][parseInt(halfIndex/2)+1] = halfRuns;
			totals[halfIndex%2][0] += parseInt(linescoreRaw[i][12]);
		  }
		  if (linescoreRaw[i][13] && linescoreRaw[i][13].indexOf('singles') > -1) {
			totals[halfIndex%2][1] += 1;
		  }
		  else if (linescoreRaw[i][13] && linescoreRaw[i][13].indexOf('doubles') > -1) {
			totals[halfIndex%2][1] += 1;
		  }
		  else if (linescoreRaw[i][13] && linescoreRaw[i][13].indexOf('triples') > -1) {
			totals[halfIndex%2][1] += 1;
		  }
		  else if (linescoreRaw[i][13] && linescoreRaw[i][13].indexOf('homers') > -1) {
			totals[halfIndex%2][1] += 1;
			if (halfIndex%2 == 0){_this.shadowRoot.querySelector('#away-extra').innerHTML += 'HR: '+linescoreRaw[i][14]+' ('+(linescoreRaw[i][12]-1)+' on)<br>';}
			else if (halfIndex%2 == 1){_this.shadowRoot.querySelector('#home-extra').innerHTML += 'HR: '+linescoreRaw[i][14]+' ('+(linescoreRaw[i][12]-1)+' on)<br>';}
		  }
		  else if (linescoreRaw[i][13] && linescoreRaw[i][13].indexOf('error') > -1) {
			totals[1 - (halfIndex%2)][2] += 1;
		  }

		  if (parseInt(linescoreRaw[i][11]) > 0) {
			currentouts += parseInt(linescoreRaw[i][11]);
		  }
		  currentTeam = linescoreRaw[i][15];
	  }
	  if (linescorearray[1].length < linescorearray[0].length) {linescorearray[1].push('x');}
	  linescorearray[0].push(totals[0][0]);
	  linescorearray[1].push(totals[1][0]);
	  linescorearray[0].push(totals[0][1]);
	  linescorearray[1].push(totals[1][1]);
	  linescorearray[0].push(totals[0][2]);
	  linescorearray[1].push(totals[1][2]);


	var th = document.createElement('th');
	th.textContent = '';
	thead.appendChild(th);
	var td = document.createElement('td');
	td.textContent = linescorearray[0][0];
	row1.appendChild(td);
	td = document.createElement('td');
	td.textContent = linescorearray[1][0];
	row2.appendChild(td);
	for (var i=1;i<linescorearray[0].length-3;i++) {
		th = document.createElement('th');
		th.textContent = i;
		thead.appendChild(th);
		td = document.createElement('td');
		td.textContent = linescorearray[0][i];
		td.id = 'pbpHalf_A-'+i;
		var contentstr = '';
		if (i-1 < playarray[0].length){
			for (var ii=0;ii<playarray[0][i-1].length;ii++){
				contentstr += playarray[0][i-1][ii] + '<br>';
			}
		}
		tippy(td, {
		  content: contentstr,
		})
		//td.addEventListener('click', e => {alert(e.target.id);});
		row1.appendChild(td);
		td = document.createElement('td');
		td.textContent = linescorearray[1][i];
		td.id = 'pbpHalf_H-'+i;
		contentstr = '';
		if (i-1 < playarray[1].length){
			for (var ii=0;ii<playarray[1][i-1].length;ii++){
				contentstr += playarray[1][i-1][ii] + '<br>';
			}
		}
		tippy(td, {
		  content: contentstr,
		})
		//td.addEventListener('click', e => {alert(e.target.id);});
		row2.appendChild(td);
	}
	['R','H','E'].forEach( x => {
		th = document.createElement('th');
		th.textContent = x;
		thead.appendChild(th);
		td = document.createElement('td');
		td.textContent = linescorearray[0][i];
		row1.appendChild(td);
		td = document.createElement('td');
		td.textContent = linescorearray[1][i];
		row2.appendChild(td);
		i++;
	});
  }
  
  offbox(batterarray) {
  	var offboxa = this.shadowRoot.querySelector('#awayoff-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	var offboxh = this.shadowRoot.querySelector('#homeoff-location');
  	var theadh = offboxh.querySelector('thead').querySelector('tr');
  	var tbodyh = offboxh.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	theadh.innerHTML = '';
  	tbodyh.innerHTML = '';
  	['Name','PA','AB','H','BB','R','RBI','K'].forEach(x => {
  		var th = document.createElement('th');
		th.textContent = x;
		theada.appendChild(th);
		th = document.createElement('th');
		th.textContent = x;
		theadh.appendChild(th);
	});
	
	var currentOrder = 0;
	var currentClass = 1;
	for (var i=1;i<batterarray.length;i++){
		if (batterarray[i].length < 10){continue;}
		var tr = document.createElement('tr');
		if (currentOrder != batterarray[i][2]) {
			currentOrder = batterarray[i][2];
			currentClass = 3 - currentClass;
			var td = document.createElement('td');
			td.textContent = batterarray[i][2]+'. '+batterarray[i][0];
			tr.appendChild(td);
			tr.classList.add("tr1");
		}
		else {
			var td = document.createElement('td');
			td.textContent = '\u00A0\u00A0\u00A0\u00A0'+batterarray[i][0];
			tr.appendChild(td);
			tr.classList.add("tr2");
		}
		
		[4,5,6,7,8,9,10].forEach( x => {
			var td = document.createElement('td');
			td.textContent = batterarray[i][x];
			tr.appendChild(td);
		});
		//tr.addEventListener('click', e => {this.tippyHalf(e);});
		tippy(tr, {
		  content: 'offbox_A-'+i,
		})
		
		if (batterarray[i][1]==0) {
			tr.id = 'offbox_A-'+i;
			tbodya.appendChild(tr);
		}
		else {
			tr.id = 'offbox_H-'+i;
			tbodyh.appendChild(tr);
		}
	}
  }
  pitchbox(pitcherarray) {
  	var offboxa = this.shadowRoot.querySelector('#awaypitcher-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	var offboxh = this.shadowRoot.querySelector('#homepitcher-location');
  	var theadh = offboxh.querySelector('thead').querySelector('tr');
  	var tbodyh = offboxh.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	theadh.innerHTML = '';
  	tbodyh.innerHTML = '';
  	['Name','IP','H','BB','R','ER','K'].forEach(x => {
  		var th = document.createElement('th');
		th.textContent = x;
		theada.appendChild(th);
		th = document.createElement('th');
		th.textContent = x;
		theadh.appendChild(th);
	});
	
	var currentOrder = 0;
	var currentClass = 1;
	for (var i=1;i<pitcherarray.length;i++){
		var tr = document.createElement('tr');
		tr.classList.add("tr1");

		[0,2,3,4,5,6,8].forEach( x => {
			var td = document.createElement('td');
			if (x != 2){td.textContent = pitcherarray[i][x];}
			else {
				var IPouts = parseInt(pitcherarray[i][x]);
				if (IPouts%3 == 0) {td.textContent = IPouts/3;}
				else if (IPouts%3 == 1 && IPouts > 3) {td.textContent = parseInt((IPouts-1)/3) + ' ⅓';}
				else if (IPouts%3 == 2 && IPouts > 3) {td.textContent = parseInt((IPouts-2)/3) + ' ⅔';}
				else if (IPouts%3 == 1) {td.textContent = '⅓';}
				else if (IPouts%3 == 2) {td.textContent = '⅔';}
				
			}
			tr.appendChild(td);
		});
		tr.addEventListener('click', e => {alert(e.target.parentNode.id);});
		
		if (pitcherarray[i][1]==0) {
			tr.id = 'pitchbox_A-'+i;
			tbodya.appendChild(tr);
		}
		else {
			tr.id = 'pitchbox_H-'+i;
			tbodyh.appendChild(tr);
		}
	}
  }
  

  
	
  
}

customElements.define('box-score', BoxScore);

class TabDNBox extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
		this.ws.onopen = function(){
			var jsonmessage = {'command':'create','src':_this.getAttribute('src')};
			_this.ws.send(JSON.stringify(jsonmessage));
			if (_this.getAttribute('autoload')){
				if (_this.usecache){
					_this.usecache = false;
					var jsonmessage = {'command':'load'};
					_this.ws.send(JSON.stringify(jsonmessage));
					var jsonmessage = { command: 'filter', formula: 'c28_4/1/2000_c28_9/1/2000@##>##<&' };
					_this.ws.send(JSON.stringify(jsonmessage));
					_this.endRow = 162;
					var jsonmessage = {'command':'print','startrow':_this.startRow,'endrow':_this.endRow};
					_this.ws.send(JSON.stringify(jsonmessage));
				}
			}
		};
		//this.createTable();
    	//this.addPaginate();
    	//this.addButtons();
		let template = document.getElementById('choosebox');
		let templateContent = template.content;
	
		const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
		
		this.shadowRoot.querySelector("#submitChg").addEventListener("mousedown", e => {this.chgBoxes()});
		
		this.boxscores = [];
		this.boxindex = 0;
		
		
	}
	
	chgBoxes() {
		var filters = "(DATE>4/1/2000 AND DATE<9/1/2000)";
		
		var team1 = this.shadowRoot.querySelector("#team1");
		var team1H = this.shadowRoot.querySelector("#home1");
		var team1A = this.shadowRoot.querySelector("#away1");
		var team2 = this.shadowRoot.querySelector("#team2");
		var team2H = this.shadowRoot.querySelector("#home2");
		var team2A = this.shadowRoot.querySelector("#away2");
		if (team1.value.length > 0){
			if (team1H.checked && team1A.checked){filters += " AND (TEAM=="+team1.value+" OR OPP=="+team1.value+")";}
			else if (team1H.checked){filters += " AND ((TEAM=="+team1.value+" AND LOC==1) OR (OPP=="+team1.value+" AND LOC==0))";}
			else if (team1A.checked){filters += " AND ((TEAM=="+team1.value+" AND LOC==0) OR (OPP=="+team1.value+" AND LOC==1))";}
		}
		if (team2.value.length > 0){
			if (team2H.checked && team2A.checked){filters += " AND (TEAM=="+team2.value+" OR OPP=="+team2.value+")";}
			else if (team2H.checked){filters += " AND ((OPP=="+team2.value+" AND LOC==0) OR (TEAM=="+team2.value+" AND LOC==1))";}
			else if (team2A.checked){filters += " AND ((OPP=="+team2.value+" AND LOC==1) OR (TEAM=="+team2.value+" AND LOC==0))";}
		}
		
		var dates = this.shadowRoot.querySelector("#dates").value.split('-');
		if (dates.length == 2){
			filters += " AND (DATE>="+dates[0]+")";
			filters += " AND (DATE<="+dates[1]+")";
		}
		else if (dates.length == 1){
			if (dates[0].length > 0){
				filters += " AND (DATE=="+dates[0]+")";
			}
		}
		
		console.log(filters);
		var filterFormula = postfixify(filters,this.colInfo);
		var jsonmessage = {'command':'filter','formula':filterFormula};
		this.ws.send(JSON.stringify(jsonmessage));
		
		var sort = this.shadowRoot.querySelector('input[name="sort"]:checked').value;
		console.log(this.colInfo);
		if (sort == "newest"){
			var jsonmessage = {'command':'pivot','pivotcol':'2','sort':'x28','columns':[]};
			this.ws.send(JSON.stringify(jsonmessage));
			jsonmessage = {'command':'print','type':'main'};
			this.ws.send(JSON.stringify(jsonmessage));
		}
		else if (sort == "oldest"){
			var jsonmessage = {'command':'pivot','pivotcol':'2','sort':'x28','columns':[]};
			this.ws.send(JSON.stringify(jsonmessage));
			jsonmessage = {'command':'print','type':'pivot@0'};
			this.ws.send(JSON.stringify(jsonmessage));
		}
		
		
		

	}
	nextBox(n=-1) {
		if (n == -1 && this.boxindex+1 < this.boxscores.length){
			this.boxindex++;
			var boxes = document.querySelectorAll('box-score');
			boxes[0].setAttribute("src",this.boxscores[this.boxindex]);
			boxes[0].setAttribute("nsrc",this.boxscores[this.boxindex+1]);
			boxes[0].setAttribute("psrc",this.boxscores[this.boxindex-1]);
			boxes[0].chgsrc();
			boxes[1].setAttribute("src",this.boxscores[this.boxindex+1]);
			boxes[1].setAttribute("nsrc",this.boxscores[this.boxindex+2]);
			boxes[1].setAttribute("psrc",this.boxscores[this.boxindex]);
			boxes[1].chgsrc();
		}
		else if (parseInt(n) > 0 && parseInt(n) < this.boxscores.length){
			this.boxindex = parseInt(n);
			var boxes = document.querySelectorAll('box-score');
			boxes[0].setAttribute("src",this.boxscores[this.boxindex]);
			boxes[0].setAttribute("nsrc",this.boxscores[this.boxindex+1]);
			boxes[0].setAttribute("psrc",this.boxscores[this.boxindex-1]);
			boxes[0].chgsrc();
			boxes[1].setAttribute("src",this.boxscores[this.boxindex+1]);
			boxes[1].setAttribute("nsrc",this.boxscores[this.boxindex+2]);
			boxes[1].setAttribute("psrc",this.boxscores[this.boxindex]);
			boxes[1].chgsrc();
		}
		
	}
	prevBox() {
		if (this.boxindex-1 >=0){
			this.boxindex--;
			var boxes = document.querySelectorAll('box-score');
			boxes[0].setAttribute("src",this.boxscores[this.boxindex]);
			boxes[0].setAttribute("nsrc",this.boxscores[this.boxindex+1]);
			boxes[0].setAttribute("psrc",this.boxscores[this.boxindex-1]);
			boxes[0].chgsrc();
			boxes[1].setAttribute("src",this.boxscores[this.boxindex+1]);
			boxes[1].setAttribute("nsrc",this.boxscores[this.boxindex+2]);
			boxes[1].setAttribute("psrc",this.boxscores[this.boxindex]);
			boxes[1].chgsrc();
		}
	}
	

	addData(retmess) {
		var boxes = document.querySelectorAll('box-score');
		var i = 0;
		this.boxscores = [];
		if (retmess[1].length > 20){ //Is full table
			for (var ii=0;ii*2 + 1<retmess[0].length;ii++) {
				this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
			}
			for (var ii=1;ii<retmess.length;ii++) {
				this.boxscores.push(retmess[ii][2]);
			}
		}
		else { //Is pivot table
			for (var ii=1;ii<retmess.length;ii++) {
				this.boxscores.push(retmess[ii][1]);
			}
		}
		boxes[0].setAttribute("src",this.boxscores[0]);
		boxes[0].setAttribute("nsrc",this.boxscores[1]);
		boxes[0].setAttribute("psrc",this.boxscores[2]);
		boxes[0].chgsrc();
		boxes[1].setAttribute("src",this.boxscores[1]);
		boxes[1].setAttribute("nsrc",this.boxscores[2]);
		boxes[1].setAttribute("psrc",this.boxscores[0]);
		boxes[1].chgsrc();
  	}
  	
  	boxFilter(e,x) {
		//if (this.currentTable != 'main'){return 0;}
		let rawFormula = "(DATE>4/1/2000 AND DATE<9/1/2000) AND (" + this.shadowRoot.querySelector("#filterFormula").value+")";
		if (rawFormula == '' || rawFormula == this.currentFilter){return 0;}
		var filterFormula;
		console.log(rawFormula);
		try {
			filterFormula = postfixify(rawFormula,this.colInfo);
		}
		catch (e) {
			return 0;
		}
		console.log(filterFormula);
		if (this.usecache){
			this.usecache = false;
			var jsonmessage = {'command':'load'};
			this.ws.send(JSON.stringify(jsonmessage));
		}
	
		if (x == 0){//mouseover Filter button
			var jsonmessage = {'command':'filter','formula':filterFormula};
			this.ws.send(JSON.stringify(jsonmessage));
			this.showit = false;
			this.foundit = false;
		}
		else if (x == 1){//mousedown
		
		}
		else if (x == 3){//mouseup
			if (this.foundit){
				this.addData(this.retdata);
				this.showit = true;
			}
			else {
				this.showit = true;
				this.foundit = true;
			}
			this.shadowRoot.querySelector("#filterFormula").value = "";
			this.currentFilter = rawFormula;
		}

	}
	
	
}

var dataBoxes = {};
customElements.define('tabdn-box', TabDNBox);


