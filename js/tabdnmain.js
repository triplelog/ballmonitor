class TabDN extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	this.colInfo = {};
    this.createTable();
    this.addPaginate();
    this.addButtons();
    this.startRow = 0;
    this.endRow = 10;
    this.usecache = true;
    this.showit = true;
    this.foundit = true;
    this.retdata = "";
    this.gtMode = false;
	this.ltMode = false;
	this.sortondown = false;
	this.currentMode = "sort";
	this.currentTable = "main";
	this.usecards = false;
    this.scrollTimeout;
    this.latestKnownScrollY = 0;
    this.currentFilter = "";
    this.pivotMode = "pivotcol";
    
    this.ws = new WebSocket('wss://tabdn.com:8080');
    
    
	this.ws.onmessage = function(evt){
		if (evt.data.substring(0,4) == 'foot') {
			if (2 == 2) {
				console.log(evt.data.substring(4,evt.data.length));
				_this.addFoot(JSON.parse(evt.data.substring(4,evt.data.length)));
				var d = new Date();
				var n = d.getTime();
				console.log(n);
			}
			else{
				
			}
		}
		else if (evt.data[0] == '['){
			if (_this.showit) {
				console.log(evt.data);
				_this.addData(JSON.parse(evt.data));
				var d = new Date();
				var n = d.getTime();
				console.log('real data:',n);
			}
			else{
				_this.retdata = JSON.parse(evt.data);
				_this.foundit = true;
			}
		}
		else{
			alert("Bad Message");
		}
	};
	
	
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
				
			}
		}
	};
	
	

  }
  
  createTable() {
  	
  	const shadowRoot = this.attachShadow({mode: 'open'});
  	shadowRoot.innerHTML += "<style>.paginate { display: inline-block;}</style>";
  	shadowRoot.innerHTML += "<style>.paginate a {color: black; float: left; padding: 2px 4px;text-decoration: none;}</style>";
  	shadowRoot.innerHTML += "<style>.paginate a.active {background-color: #4CAF50;color: white;}</style>";
  	shadowRoot.innerHTML += "<style>.paginate a:hover:not(.active) {background-color: #ddd;}</style>";
  	shadowRoot.innerHTML += "<style>.paginate a:hover {cursor: pointer;}</style>";
  	
  	var table = document.createElement('table');
  		var thead = document.createElement('thead');
  			var tr = document.createElement('tr');
  			tr.style.display = "table-row";
  			tr.style.background ='white';
			thead.appendChild(tr);
  		thead.style.background ='white';
  		table.appendChild(thead);
  		var tbody = document.createElement('tbody');
  		table.appendChild(tbody);
  		var tfoot = document.createElement('tfoot');
  		table.appendChild(tfoot);
  	table.style.overflowY = "auto";
  	table.style.overflowX = "auto";
  	table.style.maxHeight = "100vh";
  	table.style.margin = "0px";
  	//table.style.border = "1px dashed blue";
  	table.style.display = "block";
  	table.addEventListener("scroll",e => {this.scrollTable(e);});
  	//this.appendChild(table);
  	this.shadowRoot.appendChild(table);
  	
  }
  
  moveHeader(moveAmt) {
  	var thead = this.shadowRoot.querySelector("thead");
  	thead.style.transform = 'translate(0px, '+moveAmt+'px)';
  }
  
  scrollTable(e) {
  	this.latestKnownScrollY = e.target.scrollTop;
  	this.moveHeader(0);
	clearTimeout(this.scrollTimeout);
	this.scrollTimeout = setTimeout(after10,150,this.latestKnownScrollY,this);
  	
  }
  
  addPaginate() {
  	var pageDiv = document.createElement("div");
	pageDiv.classList.add('paginate');
		var link = document.createElement("a");
		link.id = "pagePrev";
		link.textContent = "<";
		link.addEventListener('mousedown',e => {this.newPage(e);});
		pageDiv.appendChild(link);
		
		link = document.createElement("a");
		link.id = "page1";
		link.textContent = "1";
		link.addEventListener('mousedown',e => {this.newPage(e);});
		link.classList.add("active");
		pageDiv.appendChild(link);
		for (var i=2;i<11;i++) {
			link = document.createElement("a");
			link.id = "page"+i;
			link.textContent = i;
			link.addEventListener('mousedown',e => {this.newPage(e);});
			pageDiv.appendChild(link);
		}
		link = document.createElement("a");
		link.id = "pageNext";
		link.textContent = ">";
		link.addEventListener('mousedown',e => {this.newPage(e);});
		pageDiv.appendChild(link);
	//pageDiv.innerHTML += ' Show: ';
	var perPage = document.createElement("input");
	perPage.setAttribute("type","number");
	perPage.setAttribute("value","10");
	perPage.style.width = "5em";
	perPage.id = "perPage";
	perPage.addEventListener("input",e => {this.setPerPage(e,0);});
	pageDiv.appendChild(perPage);
	
	var modeDropdown = document.createElement("select");
  		var option = document.createElement("option");
  		option.value = "sort";
  		option.textContent = "Sort";
  		modeDropdown.appendChild(option);
  		
  		option = document.createElement("option");
  		option.value = "newcol";
  		option.textContent = "New Column";
  		modeDropdown.appendChild(option);
  		
  		option = document.createElement("option");
  		option.value = "pivot";
  		option.textContent = "Pivot Table";
  		modeDropdown.appendChild(option);
  		
  		option = document.createElement("option");
  		option.value = "filter";
  		option.textContent = "Filter";
  		modeDropdown.appendChild(option);
  		
  		option = document.createElement("option");
  		option.value = "sum";
  		option.textContent = "Sums, ...";
  		modeDropdown.appendChild(option);
  		
  		option = document.createElement("option");
  		option.value = "arrange";
  		option.textContent = "Arrange";
  		modeDropdown.appendChild(option);
  	modeDropdown.addEventListener("change", e => {this.chgMode(e,0);});
	pageDiv.appendChild(modeDropdown);
	
	this.shadowRoot.appendChild(pageDiv);
	
  }
  
  addButtons() {
  	var columnDiv = document.createElement("div");
		var columnFormula = document.createElement("input");
		columnFormula.setAttribute("type","text");
		columnFormula.id = "columnFormula";
		columnDiv.appendChild(columnFormula);
		var columnButton = document.createElement("button");
		columnButton.classList.add('columnButton');
		columnButton.textContent = 'New Column';
		columnButton.addEventListener("mousedown", e => {this.newCol(e,0);});
		columnButton.addEventListener("mouseup", e => {this.newCol(e,1);});
		columnDiv.appendChild(columnButton);
	columnDiv.style.display = 'none';
	columnDiv.id = "columnDiv";
	this.shadowRoot.appendChild(columnDiv);
	
	var filterDiv = document.createElement("div");
		var filterFormula = document.createElement("input");
		filterFormula.setAttribute("type","text");
		filterFormula.id = "filterFormula";
		filterDiv.appendChild(filterFormula);
		var filterButton = document.createElement("button");
		filterButton.classList.add('filterButton');
		filterButton.textContent = 'Filter';
		filterButton.addEventListener("mouseover", e => {this.newFilter(e,0);});
		filterButton.addEventListener("mousedown", e => {this.newFilter(e,1);});
		filterButton.addEventListener("mouseout", e => {this.newFilter(e,2);});
		filterButton.addEventListener("mouseup", e => {this.newFilter(e,3);});
		filterDiv.appendChild(filterButton);
		var comparisons = ['>','<','='];
		for (var i=0;i<3;i++) {	
			var compButton = document.createElement("button");
			compButton.textContent = comparisons[i];
			compButton.addEventListener("click", e => {this.filterCell(e);});
			filterDiv.appendChild(compButton);
		}
	filterDiv.style.display = 'none';
	filterDiv.id = "filterDiv";
	this.shadowRoot.appendChild(filterDiv);
	
	var pivotDiv = document.createElement("div");
		[["pivotCol","Pivot Column..."],["pivotSort","Sort Column..."],["pivotColumns","Show Columns..."]].forEach( pfid => {
			var pivotFormula = document.createElement("input");
			pivotFormula.setAttribute("type","text");
			pivotFormula.id = pfid[0];
			pivotFormula.setAttribute("placeholder",pfid[1]);
			pivotDiv.appendChild(pivotFormula);
		});
		var pivotButton = document.createElement("button");
		pivotButton.classList.add('pivotButton');
		pivotButton.textContent = 'Pivot';
		pivotButton.addEventListener("mousedown", e => {this.newPivot(e,1);});
		pivotButton.addEventListener("mouseup", e => {this.newPivot(e,3);});
		pivotDiv.appendChild(pivotButton);
	pivotDiv.style.display = 'none';
	pivotDiv.id = "pivotDiv";
	this.shadowRoot.appendChild(pivotDiv);
	
	var opDiv = document.createElement("div");
		var operations = ['Sum','Mean','Max','Min'];
		for (var i=0;i<4;i++) {	
			var operButton = document.createElement("button");
			operButton.textContent = operations[i];
			operButton.addEventListener("click", e => {this.columnOperation(e);});
			opDiv.appendChild(operButton);
		}
	opDiv.style.display = 'none';
	opDiv.id = "opDiv";
	this.shadowRoot.appendChild(opDiv);
  }
  
  
  
  addFoot(retmess) {
	
	var tfoot = this.shadowRoot.querySelector('tfoot');
	var rows = tfoot.querySelectorAll('tr');
	for (var i=0;i<retmess.length;i++){
		if (rows.length <= i) {
			var newrow = document.createElement('tr');
			tfoot.appendChild(newrow);
		}
	}
	rows = tfoot.querySelectorAll('tr');
	for (var i=0;i<rows.length;i++){
		if (retmess.length <= i) {
			rows[i].style.display = 'none';
		}
		else {
			rows[i].style.display = 'table-row';
		}
	}
	
	for (var i=0;i<retmess.length;i++){

		const results = rows[i].querySelectorAll('td');
		for (var ii=0;ii<Math.max(retmess[i].length,results.length);ii++) {
			if (ii < retmess[i].length && ii < results.length) {
				results[ii].textContent = retmess[i][ii];
				results[ii].style.display = 'table-cell';
			}
			else if (ii < results.length) {
				results[ii].style.display = 'none';
			}
			else if (ii < retmess[i].length) {
				var newResult = document.createElement("td");
				newResult.textContent = retmess[i][ii];
				newResult.style.display = 'table-cell';
				rows[i].appendChild(newResult);
			}
			else {
				break;
			}
		}
	}
  }
  
  mousehead(e,x) {
  	if (this.currentMode == "pivot") {
  		this.pivot(e,x);
  	}
  	else if (this.currentMode != "arrange") {
  		this.sort(e,x);
  	}
  }
  
  pivot(e,x) {
  	if (x == 3) {
		var clickedCol = e.target.textContent;
		if (this.pivotMode == 'pivotcol'){
			this.shadowRoot.querySelector("#pivotCol").value = clickedCol;
			this.shadowRoot.querySelector("#pivotSort").focus();
			this.pivotMode = 'sortcol';
		}
		else if (this.pivotMode == 'sortcol'){
			this.shadowRoot.querySelector("#pivotSort").value = clickedCol;
			this.shadowRoot.querySelector("#pivotColumns").focus();
			this.pivotMode = 'columns';
		}
		else if (this.pivotMode == 'columns'){
			this.shadowRoot.querySelector("#pivotColumns").value += clickedCol+',';
		}
	}
  }
  
  sort(e,x) {
	var sortCol = e.target.parentNode.id.substring(7,e.target.parentNode.id.length);
	if (x==0){
		//Ignore mouseover
		if (!this.usecache){
			this.sortondown = true;
		}
	}
	else if (x==1){
		if (this.sortondown || this.usecache) {
			var jsonmessage = {'command':'sort','column':sortCol};
			this.ws.send(JSON.stringify(jsonmessage));
		}
		this.showit = false;
		this.foundit = false;
	}
	else if (x==2){
		this.sortondown = false;
	}
	else if (x==3){
	
		//Release Array and load table into memory, set usecache to false
		
		if (this.foundit){
			this.addData(this.retdata);
			this.showit = true;
		}
		else {
			this.showit = true;
			this.foundit = true;
		}
		if (this.usecache){
			this.usecache = false;
			var jsonmessage = {'command':'load'};
			this.ws.send(JSON.stringify(jsonmessage));
		}
		this.sortondown = true;
	}
  }
  
  newPage(e) {	
	var pageId = e.target.id.substring(4,);
	var cpage = 1;
	var d = new Date();
	var n = d.getTime();
	console.log('new page:',n);

	if (pageId == 'Next'){
		var diff = this.endRow - this.startRow;
		this.endRow += diff;
		this.startRow += diff;
		cpage = this.startRow / diff + 1;
	}
	else if (pageId == 'Prev') {
		var diff = this.endRow - this.startRow;
		if (this.startRow >= diff){
			this.endRow -= diff;
			this.startRow -= diff;
			cpage = this.startRow / diff + 1;
		}
		else {
			this.startRow = 0;
			this.endRow = diff;
			cpage = 1;
		}
	}
	else {
		var diff = this.endRow - this.startRow;
		this.startRow = (pageId - 1) * diff;
		this.endRow = pageId * diff;
		cpage = pageId;
	}

	var allPages = this.shadowRoot.querySelector(".paginate");
	var allPageNums = allPages.querySelectorAll("a");
	for (var i=0;i<allPageNums.length;i++) {
		if (allPageNums[i].id == "page"+cpage){
		  allPageNums[i].classList.add("active");
		}
		else {
		  allPageNums[i].classList.remove("active");
		}
	  }
	var jsonmessage = {'command':'print','startrow':this.startRow,'endrow':this.endRow};
	this.ws.send(JSON.stringify(jsonmessage));


  }
  
  newCol(e,x) {
  	//Add formula to convert
  	
  	var rawFormula = this.shadowRoot.querySelector("#columnFormula").value;
  	var colFormula;
  	var newColName = "New";
  	if (rawFormula.split(':').length>1){
  		newColName = rawFormula.split(':')[0];
  		rawFormula = rawFormula.split(':')[1];
  		
  	}
  	try {
		colFormula = postfixify(rawFormula,this.colInfo)+'@'+newColName;
	}
	catch (e) {
		return 0;
	}
	if (this.usecache){
		this.usecache = false;
		var jsonmessage = {'command':'load'};
		this.ws.send(JSON.stringify(jsonmessage));
	}
	if (x==0){ //mousedown
		
		if (this.currentTable == "pivot@0"){colFormula += "@0";}
		
		var jsonmessage = {'command':'addcol','formula':colFormula};
		this.ws.send(JSON.stringify(jsonmessage));
		this.showit = false;
		this.foundit = false;
	}
	else { //mouseup
		
		if (this.foundit){
			this.addData(this.retdata);
			this.showit = true;
		}
		else {
			this.showit = true;
			this.foundit = true;
		}
		
	}
	
  }
  
  newFilter(e,x) {
  	if (this.currentTable != 'main'){return 0;}
	let rawFormula = this.shadowRoot.querySelector("#filterFormula").value;
	if (rawFormula == '' || rawFormula == this.currentFilter){return 0;}
	var filterFormula;
	try {
		filterFormula = postfixify(rawFormula,this.colInfo);
	}
	catch (e) {
		return 0;
	}
	
	
	
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
  
  newPivot(e,x) {
  	
	let pivotCol = this.shadowRoot.querySelector("#pivotCol").value.toUpperCase();
	let pivotSortR = this.shadowRoot.querySelector("#pivotSort").value.toUpperCase();
	let pivotColumnsR = this.shadowRoot.querySelector("#pivotColumns").value.toUpperCase().split(",");
	var pivotColumns = []; var pivotSort;
	if (pivotSortR.substring(0,4)=="SUM("){pivotSort = [pivotSortR.substring(4,pivotSortR.length-1),'s'];}
	else if (pivotSortR.substring(0,4)=="MAX("){pivotSort = [pivotSortR.substring(4,pivotSortR.length-1),'x'];}
	else if (pivotSortR.substring(0,4)=="MIN("){pivotSort = [pivotSortR.substring(4,pivotSortR.length-1),'n'];}
	else if (pivotSortR.substring(0,5)=="MEAN("){pivotSort = [pivotSortR.substring(5,pivotSortR.length-1),'a'];}
	else if (pivotSortR.substring(0,6)=="FIRST("){pivotSort = [pivotSortR.substring(6,pivotSortR.length-1),'f'];}
	else if (pivotSortR.substring(0,5)=="LAST("){pivotSort = [pivotSortR.substring(5,pivotSortR.length-1),'l'];}
	else if (pivotSortR.substring(0,8)=="COUNTIF("){pivotSort = [postfixify(pivotSortR.substring(8,pivotSortR.length-1),this.colInfo),'c'];}
	else{pivotSort = [pivotSortR,'s'];}
	for (var i=0;i<pivotColumnsR.length;i++){
		if (pivotColumnsR[i].substring(0,4)=="SUM("){pivotColumns.push([pivotColumnsR[i].substring(4,pivotColumnsR[i].length-1),'s']);}
		else if (pivotColumnsR[i].substring(0,4)=="MAX("){pivotColumns.push([pivotColumnsR[i].substring(4,pivotColumnsR[i].length-1),'x']);}
		else if (pivotColumnsR[i].substring(0,4)=="MIN("){pivotColumns.push([pivotColumnsR[i].substring(4,pivotColumnsR[i].length-1),'n']);}
		else if (pivotColumnsR[i].substring(0,5)=="MEAN("){pivotColumns.push([pivotColumnsR[i].substring(5,pivotColumnsR[i].length-1),'a']);}
		else if (pivotColumnsR[i].substring(0,6)=="FIRST("){pivotColumns.push([pivotColumnsR[i].substring(6,pivotColumnsR[i].length-1),'f']);}
		else if (pivotColumnsR[i].substring(0,5)=="LAST("){pivotColumns.push([pivotColumnsR[i].substring(5,pivotColumnsR[i].length-1),'l']);}
		else if (pivotColumnsR[i].substring(0,8)=="COUNTIF("){pivotColumns.push([postfixify(pivotColumnsR[i].substring(8,pivotColumnsR[i].length-1),this.colInfo),'c']);}
		else{pivotColumns.push([pivotColumnsR[i],'s']);}
	}
	console.log(pivotColumns);
	var pivotID = -1;
	var sortID = -1;
	var colIDs = [];
	for (var ii in this.colInfo) {
		if (this.colInfo[ii].toUpperCase() == pivotCol) {pivotID = ii;}
		if (pivotSort[1] != 'c' && this.colInfo[ii].toUpperCase() == pivotSort[0]) {sortID = pivotSort[1]+ii;}
		for (var i=0;i<pivotColumns.length;i++) {
			if (pivotColumns[i][1] != 'c' && this.colInfo[ii].toUpperCase() == pivotColumns[i][0]) {colIDs.push(pivotColumns[i][1]+ii);}
		}
	}
	if (pivotSort[1] == 'c'){sortID = pivotSort[0].replace('@','|');}
	for (var i=0;i<pivotColumns.length;i++) {
		if (pivotColumns[i][1] == 'c') {colIDs.push(pivotColumns[i][0].replace('@','|'));}
	}
	if (pivotID < 0){return 0;}
	
	if (this.usecache){
		this.usecache = false;
		var jsonmessage = {'command':'load'};
		this.ws.send(JSON.stringify(jsonmessage));
	}
	
	
	if (x == 1){ //mousedown
		var jsonmessage = {'command':'pivot','pivotcol':pivotID,'sort':sortID,'columns':colIDs};
		this.ws.send(JSON.stringify(jsonmessage));
		jsonmessage = {'command':'print'};
		this.ws.send(JSON.stringify(jsonmessage));
		this.showit = false;
		this.foundit = false;
	}
	else if (x == 3){ //mouseup
		if (this.foundit){
			this.addData(this.retdata);
			this.showit = true;
		}
		else {
			this.showit = true;
			this.foundit = true;
		}
	}

  }
  
  setPerPage(e,x) {
  	var diff = parseInt(this.shadowRoot.querySelector("#perPage").value);
  	if (isNaN(diff) || diff < 1 ){return 0;}
  	this.startRow = this.startRow - (this.startRow % diff);
  	this.endRow = this.startRow + diff;
  	var cpage = this.startRow / diff + 1;
  	var allPages = this.shadowRoot.querySelector(".paginate");
	var allPageNums = allPages.querySelectorAll("a");
	for (var i=0;i<allPageNums.length;i++) {
		if (allPageNums[i].id == "page"+cpage){
		  allPageNums[i].classList.add("active");
		}
		else {
		  allPageNums[i].classList.remove("active");
		}
	}
	var jsonmessage = {'command':'print','startrow':this.startRow,'endrow':this.endRow};
	this.ws.send(JSON.stringify(jsonmessage));
  }
  
  filterCell(e) {
	this.comparisonMode = e.target.textContent;
  }
  
  columnOperation(e) {
  	var jsonmessage = {'command':e.target.textContent.toLowerCase()};
	this.ws.send(JSON.stringify(jsonmessage));
  }
  
  cellClick(e,x) {
  	if (this.comparisonMode == '>' || this.comparisonMode == '<' || this.comparisonMode == '='){
  		var cell = e.target.id;
  		var val = this.shadowRoot.querySelector('#'+cell).textContent;
  		var col = parseInt(cell.split('-')[2]);
  		var thead = this.shadowRoot.querySelector('thead');
		const headrow = thead.querySelector('tr');
		const headers = headrow.querySelectorAll('th');
		var colName = headers[col].querySelector('button').textContent;
  		if (this.shadowRoot.querySelector("#filterFormula").value != ""){
  			this.shadowRoot.querySelector("#filterFormula").value += 'AND';
  		}
  		this.shadowRoot.querySelector("#filterFormula").value += colName.toUpperCase()+this.comparisonMode+val;  
  	}
  }
  
  chgMode(e,x) {
  	this.currentMode = e.target.value;
  	['pivotDiv','filterDiv','opDiv','columnDiv'].forEach( tmpDiv => {this.shadowRoot.querySelector('#'+tmpDiv).style.display = 'none';});
  	if (this.currentMode == 'newcol') {this.shadowRoot.querySelector('#columnDiv').style.display = 'inline-block';}
  	else if (this.currentMode == 'filter') {this.shadowRoot.querySelector('#filterDiv').style.display = 'inline-block';}
  	else if (this.currentMode == 'pivot') {this.pivotMode = "pivotcol"; this.shadowRoot.querySelector('#pivotDiv').style.display = 'inline-block'; this.shadowRoot.querySelector("#pivotCol").focus();}
  	else if (this.currentMode == 'sum') {this.shadowRoot.querySelector('#opDiv').style.display = 'inline-block';}
  	if (this.usecache){
		this.usecache = false;
		var jsonmessage = {'command':'load'};
		this.ws.send(JSON.stringify(jsonmessage));
	}
  }
  
  dragColumn(e,x) {
  	if (this.currentMode == 'arrange') {
  		e.dataTransfer.setData("text", e.target.parentNode.id);
  		e.dataTransfer.dropEffect = "move";
  	}
  }
  
  dropColumn(e,x) {
    if (this.currentMode == 'arrange') {
    	if (e.dataTransfer.getData("text").substring(7,) != e.target.parentNode.id.substring(7,)){
    		var jsonmessage = {'command':'display','column':e.dataTransfer.getData("text").substring(7,),'location':'-3'};
			if (x == 1){
				jsonmessage.location = e.target.parentNode.id.substring(7,);
			}
			this.ws.send(JSON.stringify(jsonmessage));
		}
    }
  }
	
  
}
