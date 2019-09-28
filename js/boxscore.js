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
  	if (this.getAttribute('src') == null) {return 0;}
  	else {
  		if (this.getAttribute('src') == this.dataFiles.prev.id) {
  			if (this.getAttribute('nsrc') == this.dataFiles.current.id) {
  				this.dataFiles.next = this.dataFiles.current;
  			}
  			else {
  				this.dataFiles.next = {id:this.getAttribute('nsrc')};
  			}
  			this.dataFiles.current = this.dataFiles.prev;
  			this.dataFiles.prev = {id:this.getAttribute('psrc')};
  		}
  		else if (this.getAttribute('src') == this.dataFiles.next.id) {
  			if (this.getAttribute('psrc') == this.dataFiles.current.id) {
  				this.dataFiles.prev = this.dataFiles.current;
  			}
  			else {
  				this.dataFiles.prev = {id:this.getAttribute('psrc')};
  			}
  			this.dataFiles.current = this.dataFiles.next;
  			this.dataFiles.next = {id:this.getAttribute('nsrc')};
  		}
  		else {
  			this.dataFiles.prev = {id:this.getAttribute('psrc')};
  			this.dataFiles.next = {id:this.getAttribute('nsrc')};
  			this.dataFiles.current = {id:this.getAttribute('src')};
  		}
  	}
    
    this.style.opacity = 0;
    if (!this.dataFiles.current.hasOwnProperty('batters')){
    	this.loadbatters(this.dataFiles.current.id,true);
    }
    else {
    	console.log("already loaded",this.dataFiles.current.id);
    	_this.offbox(_this.dataFiles.current.batters);
		if (_this.dataFiles.current.hasOwnProperty('pitchers') && _this.dataFiles.current.hasOwnProperty('plays') && _this.dataFiles.current.hasOwnProperty('info')){
			_this.style.opacity = 1;
		}
    }
    if (!this.dataFiles.current.hasOwnProperty('pitchers')){
    	this.loadpitchers(this.dataFiles.current.id,true);
    }
    else {
    	_this.pitchbox(_this.dataFiles.current.pitchers);
		if (_this.dataFiles.current.hasOwnProperty('batters') && _this.dataFiles.current.hasOwnProperty('plays') && _this.dataFiles.current.hasOwnProperty('info')){
			_this.style.opacity = 1;
		}
    }
    if (!this.dataFiles.current.hasOwnProperty('info')){
    	this.loadinfo(this.dataFiles.current.id,true);
    }
    else {
    	_this.linescore(_this.dataFiles.current.info);
		if (_this.dataFiles.current.hasOwnProperty('batters') && _this.dataFiles.current.hasOwnProperty('plays') && _this.dataFiles.current.hasOwnProperty('pitchers')){
			_this.style.opacity = 1;
		}
    }
    
    if (!this.dataFiles.next.hasOwnProperty('batters')){
    	this.loadbatters(this.dataFiles.next.id,false);
    }
    if (!this.dataFiles.next.hasOwnProperty('pitchers')){
    	this.loadpitchers(this.dataFiles.next.id,false);
    }
    if (!this.dataFiles.next.hasOwnProperty('info')){
    	this.loadinfo(this.dataFiles.next.id,false);
    }
    if (!this.dataFiles.prev.hasOwnProperty('batters')){
    	this.loadbatters(this.dataFiles.prev.id,false);
    }
    if (!this.dataFiles.prev.hasOwnProperty('pitchers')){
    	this.loadpitchers(this.dataFiles.prev.id,false);
    }
    if (!this.dataFiles.prev.hasOwnProperty('info')){
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
			_this.dataFiles.current.batters = Papa.parse(jsonFile2.responseText).data;
			if (todisplay){
				_this.offbox(_this.dataFiles.current.batters);
				if (_this.dataFiles.current.hasOwnProperty('pitchers') && _this.dataFiles.current.hasOwnProperty('plays') && _this.dataFiles.current.hasOwnProperty('info')){
					_this.style.opacity = 1;
				}
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
			_this.dataFiles.current.pitchers = Papa.parse(jsonFile1.responseText).data;
			if (todisplay){
				_this.pitchbox(_this.dataFiles.current.pitchers);
				if (_this.dataFiles.current.hasOwnProperty('batters') && _this.dataFiles.current.hasOwnProperty('plays') && _this.dataFiles.current.hasOwnProperty('info')){
					_this.style.opacity = 1;
				}
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
			_this.dataFiles.current.info = Papa.parse(jsonFile3.responseText).data;
			_this.linescore(_this.dataFiles.current.info,todisplay);
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
			_this.dataFiles.current.plays = Papa.parse(jsonFile4.responseText).data;
			if (todisplay){
				_this.fillscore(_this.dataFiles.current.plays,awayteam,hometeam);
				if (_this.dataFiles.current.hasOwnProperty('batters') && _this.dataFiles.current.hasOwnProperty('info') && _this.dataFiles.current.hasOwnProperty('pitchers')){
					_this.style.opacity = 1;
				}
			}
		}
	 }
  }
  linescore(gameinfo,todisplay=false) {
  	var _this = this;
  	var awayteam = "Away";
	var hometeam = "Home";
  	for (var i=0;i<gameinfo.length;i++){
  		if (gameinfo[i][1] == 'visteam') {awayteam = gameinfo[i][2];}
  		else if (gameinfo[i][1] == 'hometeam') {hometeam = gameinfo[i][2];}
  	}
  	
  	if (!this.dataFiles.current.hasOwnProperty('plays')){
  		this.loadplays(this.dataFiles.current.id,awayteam,hometeam,todisplay);
	}
	else if (todisplay){
		_this.fillscore(_this.dataFiles.current.plays,awayteam,hometeam);
		if (_this.dataFiles.current.hasOwnProperty('batters') && _this.dataFiles.current.hasOwnProperty('info') && _this.dataFiles.current.hasOwnProperty('pitchers')){
			_this.style.opacity = 1;
		}
	}
  	
  	
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
			currentouts = 0;
		  }
		  else if (linescoreRaw[i][15] == '1' && currentTeam == '0') {
			halfRuns = 0;
			halfIndex += 1;
			linescorearray[1].push(0);
			currentouts = 0;
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
		td.addEventListener('click', e => {alert(e.target.id);});
		row1.appendChild(td);
		td = document.createElement('td');
		td.textContent = linescorearray[1][i];
		td.id = 'pbpHalf_H-'+i;
		td.addEventListener('click', e => {alert(e.target.id);});
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
			batterarray[i][0]=batterarray[i][2]+'. '+batterarray[i][0];
			tr.classList.add("tr1");
		}
		else {
			batterarray[i][0]='\u00A0\u00A0\u00A0\u00A0\u00A0'+batterarray[i][0];
			tr.classList.add("tr2");
		}
		
		[0,4,5,6,7,8,9,10].forEach( x => {
			var td = document.createElement('td');
			td.textContent = batterarray[i][x];
			tr.appendChild(td);
		});
		tr.addEventListener('click', e => {alert(e.target.parentNode.id);});
		
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
		this.createTable();
    	//this.addPaginate();
    	//this.addButtons();
		this.addSortBox();
		this.addFilterBox();
		
		
		
		this.boxscores = [];
		this.boxindex = 0;
		
	}
	
	addSortBox() {
		var sortDiv = document.createElement("div");
			var sortFormula = document.createElement("input");
			sortFormula.setAttribute("type","text");
			sortFormula.id = "sortFormula";
			sortDiv.appendChild(sortFormula);
			var sortButton = document.createElement("button");
			sortButton.classList.add('sortButton');
			sortButton.textContent = 'Sort';
			sortButton.addEventListener("mouseover", e => {this.newSort(e,0);});
			sortButton.addEventListener("mousedown", e => {this.newSort(e,1);});
			sortButton.addEventListener("mouseout", e => {this.newSort(e,2);});
			sortButton.addEventListener("mouseup", e => {this.newSort(e,3);});
			sortDiv.appendChild(sortButton);
		sortDiv.style.display = 'inline-block';
		sortDiv.id = "sortDiv";
		this.shadowRoot.appendChild(sortDiv);
	}
	nextBox() {
		if (this.boxindex+1 < this.boxscores.length){
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
	
	addFilterBox() {
		var filterDiv = document.createElement("div");
			var filterFormula = document.createElement("input");
			filterFormula.setAttribute("type","text");
			filterFormula.id = "filterFormula";
			filterDiv.appendChild(filterFormula);
			var filterButton = document.createElement("button");
			filterButton.classList.add('filterButton');
			filterButton.textContent = 'Filter';
			filterButton.addEventListener("mouseover", e => {this.boxFilter(e,0);});
			filterButton.addEventListener("mousedown", e => {this.boxFilter(e,1);});
			filterButton.addEventListener("mouseout", e => {this.boxFilter(e,2);});
			filterButton.addEventListener("mouseup", e => {this.boxFilter(e,3);});
			filterDiv.appendChild(filterButton);
		filterDiv.style.display = 'inline-block';
		filterDiv.id = "filterDiv";
		this.shadowRoot.appendChild(filterDiv);
	}
	addData(retmess) {
		var boxes = document.querySelectorAll('box-score');
		var i = 0;
		this.boxscores = [];
		for (var ii=0;ii*2 + 1<retmess[0].length;ii++) {
			this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
		}
		for (var ii=1;ii<retmess.length;ii++) {
			this.boxscores.push(retmess[ii][2]);
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

customElements.define('tabdn-box', TabDNBox);


