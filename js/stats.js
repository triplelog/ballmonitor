class StatsStats extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	
	
	let template = document.getElementById('stats');
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

customElements.define('stats-stats', StatsStats);

class TabDNStats extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
		this.createTable();
    	this.addPaginate(false);
    	this.addOptions();
    	//this.addButtons();
    	this.ws.onopen = function(){
			var jsonmessage = {'command':'create','src':_this.getAttribute('src')};
			_this.ws.send(JSON.stringify(jsonmessage));
			if (_this.getAttribute('autoload')){
				if (_this.usecache){
					_this.usecache = false;
					var jsonmessage = {'command':'load'};
					_this.ws.send(JSON.stringify(jsonmessage));
					
					jsonmessage = {'command':'print','startrow':_this.startRow,'endrow':_this.endRow};
					_this.ws.send(JSON.stringify(jsonmessage));
					
					jsonmessage = {'command':'display','column':'3|4|5|18|19|20|21|22','location':'-3'};
					_this.ws.send(JSON.stringify(jsonmessage));
					
				
				}
			}
		};
    	
	}
	
	sendOptions(tags,filter,toggles) {
		console.log(tags);
		console.log(filter);
		console.log(toggles);
		var jsonmessage = {'command':'filter','formula':filter};
		this.ws.send(JSON.stringify(jsonmessage));
		jsonmessage = {'command':'print','startrow':this.startRow,'endrow':this.endRow};
		this.ws.send(JSON.stringify(jsonmessage));
	}
	addOptions() {
		var pageDiv = this.shadowRoot.querySelector('#perPage').parentNode;
		var editButton = document.createElement('button');
		editButton.textContent = 'Options';
		editButton.style.display = 'none';
		editButton.id = 'editButton';
		editButton.addEventListener('click',e => {this.showOptions();});
		pageDiv.appendChild(editButton);
	}
	hideOptions() {
		this.shadowRoot.querySelector('#editButton').style.display = 'inline-block';
	}
	showOptions() {
		this.shadowRoot.querySelector('#editButton').style.display = 'none';
		document.querySelector('#formData').classList.remove('hidden');
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

customElements.define('tabdn-stats', TabDNStats);

var input = document.querySelector('input[name=columns]');
var tagify = new Tagify(input);
tagify.on('add', onAddTag);
  
function onAddTag(e) {

	var tagFormula = e.detail.data.value;
	//Validate Filter by postfixifying
	if (tagFormula.length == 0){
		e.detail.tag.style.border = '0px';
		return;
	}
	if (postfixify(tagFormula,colInfo,false)){
		e.detail.tag.style.border = '1px solid green';
	}
	else {
		e.detail.tag.style.border = '1px solid red';
	}
}

var drake = dragula([document.querySelector('.tagify')], {
  removeOnSpill: false
});


var slider = document.querySelector('#years');
slider.setAttribute('value','1900,2020');
slider.setAttribute('min','1900');

slider.setAttribute('max','2020');
multirange(slider);

var colInfo = {"1":"pid","2":"game","3":"IPouts","4":"H","5":"BB","6":"R","7":"ER","8":"PC","9":"K","10":"HR","11":"1B","12":"2B","13":"3B","14":"WP","15":"HBP","16":"PA","17":"AB","18":"BK","19":"SH","20":"SF","21":"IBB","22":"team","23":"opp","24":"loc","25":"age","26":"bloc","27":"regpost","28":"date","-1":"Rk"};



function validateFilter() {
	var filterFormula = document.querySelector('#filter').value;
	//Validate Filter by postfixifying
	if (filterFormula.length == 0){
		document.querySelector('#filter').style.background = 'rgba(0,0,0,0)';
		return;
	}
	if (postfixify(filterFormula,colInfo,false)){
		document.querySelector('#filter').style.background = 'rgba(0,255,0,.1)';
	}
	else {
		document.querySelector('#filter').style.background = 'rgba(255,0,0,.1)';
	}
}

function submitOptions() {
	//Get tags
	var tagNodes = document.querySelector('.tagify').childNodes;
	var tags = [];
	for (var i=0;i<tagNodes.length;i++){
		if (tagNodes[i].tagName == 'TAG'){
			tags.push(tagNodes[i].title);
		}
	}
	//console.log(tags)
	//Get Years
	var filter = '';
	if (parseInt(slider.valueLow) > 1900){
		filter += '(YEAR>='+slider.valueLow+')';
	}
	if (parseInt(slider.valueHigh) < 2020){
		if (filter.length > 0){filter += ' AND ';}
		filter += '(YEAR<='+slider.valueHigh+')';
	}

	//Get Filters
	var filterFormula = document.querySelector('#filter').value;
	if (filterFormula.length > 0){
		if (filter.length > 0){filter += ' AND ';}
		filter += '(' + filterFormula + ')';
	}
	filter = postfixify(filter,colInfo)
	//console.log(filter);
	//Get Toggles
	var toggles = [];
	var borp = document.querySelectorAll('input[name=borp]');
	for (var i=0;i<borp.length;i++){
		if (borp[i].checked){
			toggles.push(borp[i].id);
			break;
		}
	}
	var cors = document.querySelectorAll('input[name=cors]');
	for (var i=0;i<cors.length;i++){
		if (cors[i].checked){
			toggles.push(cors[i].id);
			break;
		}
	}
	var yort = document.querySelectorAll('input[name=yort]');
	for (var i=0;i<yort.length;i++){
		if (yort[i].checked){
			toggles.push(yort[i].id);
			break;
		}
	}
	//Submit
	var tabdnStats = document.querySelector('tabdn-stats');
	tabdnStats.sendOptions(tags,filter,toggles);
	
	
}

function hideOptions() {
	document.getElementById('formData').classList.add('hidden');
	var tabdnStats = document.querySelector('tabdn-stats');
	tabdnStats.hideOptions();
}
