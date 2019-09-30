class PlayerStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	this.chgsrc();
	let template = document.getElementById('player');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));

	

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
            _this.stats(Papa.parse(jsonFile.responseText).data);
        }
     }
    
  }
  
  stats(statarray) {
  	var offboxa = this.shadowRoot.querySelector('#career-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	var statobjects = {};
  	
  	var th = document.createElement('th');
	th.textContent = 'Month';
	theada.appendChild(th);

  	[['PA','PA'],['AB','AB'],['H','H'],['BB','BB'],['R','R'],['RBI','RBI'],['K','K'],['HR','HR']].forEach(x => {
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
	var years = {total:[0,0,0,0,0,0,0]};
	for (var i=1;i<statarray.length;i++){
		if (statarray[i].length < 10){continue;}
		var year = statarray[i][0].substring(0,4);
		if (years.hasOwnProperty(year)){
			
		}
		else {
			years[year] = [0,0,0,0,0,0,0];
		}
		
		var ii = 0;
		for(var stat in statobjects) {
			if (parseInt(statarray[i][27])==1) {
				years[year][ii] += parseInt(statarray[i][statobjects[stat]]);
				years.total[ii] += parseInt(statarray[i][statobjects[stat]]);
			}
			ii++;
		}

	}
	for(var year in years){
		if (year == 'total'){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		var td = document.createElement('td');
		td.textContent = year;
		tr.appendChild(td);
		var ii = 0;
		for (var stat in statobjects) {
			td = document.createElement('td');
			td.textContent = years[year][ii];
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
  	var statobjects = {};
  	var offboxa = this.shadowRoot.querySelector('#season-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	
  	var th = document.createElement('th');
	th.textContent = 'Month';
	theada.appendChild(th);

  	[['PA','PA'],['AB','AB'],['H','H'],['BB','BB'],['R','R'],['RBI','RBI'],['K','K'],['HR','HR']].forEach(x => {
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
	var months = {total:[0,0,0,0,0,0,0]};
	for (var i=1;i<statarray.length;i++){
		if (statarray[i].length < 10){continue;}
		var year = statarray[i][0].substring(0,4);
		if (parseInt(year) != parseInt(seasonYear)){continue;}
		var month = statarray[i][0].substring(4,6);
		if (months.hasOwnProperty(month)){
			
		}
		else {
			months[month] = [0,0,0,0,0,0,0];
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

