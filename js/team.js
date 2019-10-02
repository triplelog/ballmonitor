class TeamStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	this.chgsrc();
	let template = document.getElementById('team');
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
  	this.displayStats.push([postfixify(cformula,this.colInfo),cname]);
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
	for(var year in years){
		if (year == 'total'){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		var td = document.createElement('td');
		td.textContent = year;
		tr.appendChild(td);
		
		this.displayStats.forEach(x => {
			td = document.createElement('td');
			var nc = parseInt(postfixify(x[1],this.colInfo).split('@')[0].substring(1,));
			var ncd = solvepostfixjs(years[year],x[0])
			td.textContent = ncd;
			years[year][nc] = ncd;
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

customElements.define('team-stats', TeamStats);

class TabDNTeam extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
		this.createTable();
    	this.addPaginate();
    	this.addButtons();
    	this.ws.onopen = function(){
			var jsonmessage = {'command':'create','src':_this.getAttribute('src')};
			_this.ws.send(JSON.stringify(jsonmessage));
			if (_this.getAttribute('autoload')){
				if (_this.usecache){
					_this.usecache = false;
					var jsonmessage = {'command':'load'};
					_this.ws.send(JSON.stringify(jsonmessage));
					
					var jsonmessage = { command: 'filter', formula: 'c4_ATL@##=' };
					_this.ws.send(JSON.stringify(jsonmessage));
					var jsonmessage = {'command':'print','startrow':_this.startRow,'endrow':_this.endRow};
					_this.ws.send(JSON.stringify(jsonmessage));
					
					var jsonmessage = {'command':'display','column':'3|4|5|18|19|20|21|22','location':'-3'};
					_this.ws.send(JSON.stringify(jsonmessage));
					
				
				}
			}
		};
    	
	}
	
	 addData(retmess) {
		var table = this.shadowRoot.querySelector('table');
		table.style.maxWidth = (this.parentNode.clientWidth-20)+"px";
		table.style.maxHeight = (this.parentNode.clientHeight-40)+"px";
		this.style.maxWidth = (this.parentNode.clientWidth-20)+"px";
		this.style.maxHeight = (this.parentNode.clientHeight-1)+"px";
	
		if (retmess[0][0].substring(0,5)=="Pivot"){
			this.currentTable = "pivot@" + retmess[0][0].substring(6,retmess[0][0].length-2);
			retmess[0][0] = "Rk";
		}
		var thead = this.shadowRoot.querySelector('thead');
		const headrow = thead.querySelector('tr');
		const headers = headrow.querySelectorAll('th');
		for (var ii=0;ii*2 + 1<Math.max(retmess[0].length,headers.length*2 + 1);ii++) {
			if (ii*2 + 1 < retmess[0].length && ii < headers.length) {
				headers[ii].querySelector('button').textContent = retmess[0][ii*2];
				headers[ii].id = "cHeader"+retmess[0][ii*2 + 1];
				headers[ii].style.display = 'table-cell';
				this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
			}
			else if (ii < headers.length) {
				headers[ii].style.display = 'none';
			}
			else if (ii*2 + 1 < retmess[0].length) {
				var headerCell = document.createElement("th");
				var newHeader = document.createElement("button");
				newHeader.textContent = retmess[0][ii*2];
				newHeader.style.display = 'inline-block';
				newHeader.style.height = '100%';
				newHeader.style.width = '100%';
				newHeader.addEventListener('mouseover',e => {this.mousehead(e,0);});
				newHeader.addEventListener('mousedown',e => {this.mousehead(e,1);});
				newHeader.addEventListener('mouseout',e => {this.mousehead(e,2);});
				newHeader.addEventListener('mouseup',e => {this.mousehead(e,3);});
				newHeader.setAttribute("draggable","true");
				newHeader.addEventListener('dragstart',e => {this.dragColumn(e,0);});
				newHeader.addEventListener("dragover", e => {e.preventDefault();});
				newHeader.addEventListener("drop", e => {e.preventDefault(); this.dropColumn(e,1);});
				headerCell.id = "cHeader"+retmess[0][ii*2 + 1];
				headerCell.style.display = 'table-cell';
				headerCell.classList.add("th-sm");
				this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
				headerCell.appendChild(newHeader);
				headrow.appendChild(headerCell);
			}
			else {
				break;
			}
		}
	
		var tbody = this.shadowRoot.querySelector('tbody');
		var rows = tbody.querySelectorAll('tr');
		for (var i=0;i<retmess.length-1;i++){
			if (rows.length <= i) {
				var newrow = document.createElement('tr');
				newrow.addEventListener("dragover", e => {e.preventDefault();});
				newrow.addEventListener("drop", e => {e.preventDefault(); this.dropColumn(e,0);});
				tbody.appendChild(newrow);
			}
		}
		rows = tbody.querySelectorAll('tr');
		for (var i=0;i<rows.length;i++){
			if (retmess.length-1 <= i) {
				rows[i].style.display = 'none';
			}
			else {
				rows[i].style.display = 'table-row';
			}
		}
	
		for (var i=0;i<retmess.length-1;i++){

			const results = rows[i].querySelectorAll('td');
			for (var ii=0;ii<Math.max(retmess[i+1].length,results.length);ii++) {
				if (ii < retmess[i+1].length && ii < results.length) {
					results[ii].textContent = retmess[i+1][ii]; //add one because of header
					results[ii].style.display = 'table-cell';
				}
				else if (ii < results.length) {
					results[ii].style.display = 'none';
				}
				else if (ii < retmess[i+1].length) {
					var newResult = document.createElement("td");
					newResult.textContent = retmess[i+1][ii];
					newResult.style.display = 'table-cell';
					newResult.id = 'cell-'+i+'-'+ii;
					newResult.addEventListener("click",e => {this.cellClick(e,0);});
					rows[i].appendChild(newResult);
				}
				else {
					break;
				}
			}
		}

    }
	
	
}

customElements.define('tabdn-team', TabDNTeam);

