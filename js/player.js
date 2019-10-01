class PlayerStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	this.chgsrc();
	let template = document.getElementById('player');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
	this.displayStats = [];
  	this.zeroStats = [];
  	for (var i=0;i<this.displayStats.length;i++){
  		this.zeroStats.push(0);
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
            _this.addColumn("H/AB","AVG");
        }
     }
    
  }
  
  addColumn(cformula,cname) {
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
  	this.displayStats.push([postfixify(cformula,this.colInfo),cname]);
  	if (postfixify(cformula,this.colInfo).split('_').length>1){
  		this.colInfo[i] = cname;
  	}
  	this.stats(this.playerStats);
  	this.seasonstats(this.currentYear);
  }
  
  stats(statarray) {
  	var offboxa = this.shadowRoot.querySelector('#career-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	var statobjects = [];
  	
  	
  	var th = document.createElement('th');
	th.textContent = 'Year';
	theada.appendChild(th);
  	this.displayStats.forEach(x => {
  		th = document.createElement('th');
		th.textContent = x[1];
		theada.appendChild(th);
		var cols = x[0].split('@')[0].split('_');
		for (var ii=0;ii<cols.length;ii++){
			statobjects.push(parseInt(cols[ii].substring(1,)));
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
		var year = statarray[i][0].substring(0,4);
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
	for(var year in years){
		if (year == 'total'){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		var td = document.createElement('td');
		td.textContent = year;
		tr.appendChild(td);
		
		this.displayStats.forEach(x => {
			td = document.createElement('td');
			td.textContent = solvepostfixjs(years[year],x[0]);
			tr.appendChild(td);
		});
		

		tbodya.appendChild(tr);
	}
	var tr = document.createElement('tr');
	tr.classList.add("tr1");
	var td = document.createElement('td');
	td.textContent = 'Total';
	tr.appendChild(td);
	var ii = 0;
	for (var stat in statobjects) {
		td = document.createElement('td');
		td.textContent =  years.total[ii];
		tr.appendChild(td);
		ii++;
	}
	
	this.playerStats = statarray;
	this.seasonstats(parseInt(statarray[1][0].substring(0,4)));
	tbodya.appendChild(tr);
  }
  
  seasonstats(seasonYear) {
  	var statarray = this.playerStats;
  	this.currentYear = seasonYear;
  	var statobjects = {};
  	var offboxa = this.shadowRoot.querySelector('#season-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	
  	var th = document.createElement('th');
	th.textContent = 'Month';
	theada.appendChild(th);

  	this.displayStats.forEach(x => {
  		th = document.createElement('th');
		th.textContent = x[1];
		theada.appendChild(th);
		for (var i = 0;i<statarray[0].length;i++){
			if (statarray[0][i]==x[0]){
				statobjects[x[0]]=i;
				break;
			}
		}
	});
	var currentOrder = 0;
	var currentClass = 1;
	var months = {total:this.zeroStats.slice()};
	for (var i=1;i<statarray.length;i++){
		if (statarray[i].length < 10){continue;}
		var year = statarray[i][0].substring(0,4);
		if (parseInt(year) != parseInt(seasonYear)){continue;}
		var month = statarray[i][0].substring(4,6);
		if (months.hasOwnProperty(month)){
			
		}
		else {
			months[month] = this.zeroStats.slice();
		}
		
		var ii = 0;
		for(var stat in statobjects) {
			if (parseInt(statarray[i][27])==1) {
				months[month][ii] += parseInt(statarray[i][statobjects[stat]]);
				months.total[ii] += parseInt(statarray[i][statobjects[stat]]);
			}
			ii++;
		}

	}
	for(month in months){
		if (month == 'total'){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		var td = document.createElement('td');
		td.textContent = monthnames[parseInt(month)];
		tr.appendChild(td);
		var ii = 0;
		for (var stat in statobjects) {
			td = document.createElement('td');
			td.textContent = months[month][ii];
			tr.appendChild(td);
			ii++;
		}
		

		tbodya.appendChild(tr);
	}
	var tr = document.createElement('tr');
	tr.classList.add("tr1");
	var td = document.createElement('td');
	td.textContent = 'Total';
	tr.appendChild(td);
	var ii = 0;
	for (var stat in statobjects) {
		td = document.createElement('td');
		td.textContent = months.total[ii];
		tr.appendChild(td);
		ii++;
	}
	

	tbodya.appendChild(tr);
  }
  
	
  
}

customElements.define('player-stats', PlayerStats);

class TabDNPlayer extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
		this.createTable();
    	//this.addPaginate();
    	//this.addButtons();
	}
	
	 addData(retmess) {
		var players = document.querySelectorAll('player-stats');
		var i = 0;
		for (var ii=0;ii*2 + 1<retmess[0].length;ii++) {
			this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
		}
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

    }
	
	
}

customElements.define('tabdn-player', TabDNPlayer);

