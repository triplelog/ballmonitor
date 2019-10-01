class PlayerStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	
	
	let template = document.getElementById('player');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
	this.displayStats = [];
  	
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

