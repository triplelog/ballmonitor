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
            _this.currentYear = parseInt(_this.playerStats[1][0].substring(0,4));
            _this.addColumn("H","H");
            _this.addColumn("AB","AB");
            _this.addColumn("H/AB","AVG");
            _this.addColumn("AVG+1","AAA");
            _this.stats(0);
  			_this.stats(_this.currentYear);
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
  	this.displayStats.push([postfixify(cformula,this.colInfo),cname,cformula]);
  	if (postfixify(cformula,this.colInfo).split('_').length>1){
  		this.playerStats[0].push(cname);
  	}
  	
  }
  
  stats(seasonYear=0) {
    var statarray = this.playerStats;
    
  	var offboxa = this.shadowRoot.querySelector('#career-location');
  	if (seasonYear != 0){
		this.currentYear = seasonYear;
		offboxa = this.shadowRoot.querySelector('#season-location');
  	}
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	var statobjects = [];
  	
  	
  	var th = document.createElement('th');
  	if (seasonYear != 0){
		th.textContent = 'Month';
	}
	else {
		th.textContent = 'Year';
	}
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
	this.sortInfo = [[1,-1,''],[0,1,'']];
	for(var year in years){
		if (year == 'total'){continue;}
		var oneyear = [year];
		this.displayStats.forEach(x => {
			var nc = parseInt(postfixify(x[1],this.colInfo).split('@')[0].substring(1,));
			var ncd = solvepostfixjs(years[year],x[0]);
			years[year][nc] = ncd;
			oneyear.push(ncd);
		});
		orderedData.push(oneyear);
	}
	if (seasonYear == 0) {
		if (this.sortInfo[0][1] == -1){orderedData.sort((a, b) => b[this.sortInfo[0][0]] - a[this.sortInfo[0][0]]);}
		else {orderedData.sort((a, b) => a[this.sortInfo[0][0]] - b[this.sortInfo[0][0]]);}
	}
	else {
		if (this.sortInfo[1][1] == -1){orderedData.sort((a, b) => b[this.sortInfo[1][0]] - a[this.sortInfo[1][0]]);}
		else {orderedData.sort((a, b) => a[this.sortInfo[1][0]] - b[this.sortInfo[1][0]]);}
	}
	for(var i=0;i<orderedData.length;i++){
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		for (var ii=0;ii<orderedData[i].length;ii++){
			var td = document.createElement('td');
			td.textContent = orderedData[i][ii];
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
		td.textContent = ncd;
		years.total[nc] = ncd;
		tr.appendChild(td);
		ii++;
	});
	
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

