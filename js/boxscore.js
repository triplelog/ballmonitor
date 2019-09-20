class BoxScore extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	var url = 'box/ATL197309260batterbox.csv';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();

    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            _this.offbox(Papa.parse(jsonFile.responseText).data);
        }
     }
    var url2 = 'box/ATL197309260pitcherbox.csv';
	var jsonFile2 = new XMLHttpRequest();
    jsonFile2.open("GET",url2,true);
    jsonFile2.send();

    jsonFile2.onreadystatechange = function() {
        if (jsonFile2.readyState== 4 && jsonFile2.status == 200) {
            _this.pitchbox(Papa.parse(jsonFile2.responseText).data);
        }
     }
	let template = document.getElementById('boxscore');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
    
    this.linescore([['A',0,0,0,0,0],['B',1,0,1,0,0]]);
    //this.offbox([[['Name1',0,0,0,0,0,0,0],['Name2',0,0,0,0,0,0,0]],[['Name3',0,0,0,0,0,0,0],['Name4',0,0,0,0,0,0,0]]]);
    /*
    this.ws = new WebSocket('ws://155.138.201.160:8080');
    
    
	this.ws.onmessage = function(evt){
		
	};
	
	
	this.ws.onopen = function(){
		
	};
	*/
	

  }
  
  linescore(linescorearray) {
  	var linescore = this.shadowRoot.querySelector('#linescore-location');
  	var thead = linescore.querySelector('thead').querySelector('tr');
  	var row1 = linescore.querySelector('tbody').querySelectorAll('tr')[0];
  	var row2 = linescore.querySelector('tbody').querySelectorAll('tr')[1];
  	thead.innerHTML = '';
  	row1.innerHTML = '';
  	row2.innerHTML = '';
  	var th = document.createElement('th');
  	th.textContent = 'Team';
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
	console.log(batterarray);
	
	var currentOrder = 0;
	var currentClass = 1;
	for (var i=1;i<batterarray.length;i++){
		var tr = document.createElement('tr');
		if (currentOrder != batterarray[i][2]) {
			currentOrder = batterarray[i][2];
			currentClass = 3 - currentClass;
			tr.classList.add("tr1");
		}
		else {
			batterarray[i][0]='\u00A0'+batterarray[i][0];
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
  	['Name','PA','AB','H','BB','R','RBI','K'].forEach(x => {
  		var th = document.createElement('th');
		th.textContent = x;
		theada.appendChild(th);
		th = document.createElement('th');
		th.textContent = x;
		theadh.appendChild(th);
	});
	console.log(pitcherarray);
	
	var currentOrder = 0;
	var currentClass = 1;
	for (var i=1;i<pitcherarray.length;i++){
		var tr = document.createElement('tr');
		if (currentOrder != pitcherarray[i][2]) {
			currentOrder = pitcherarray[i][2];
			currentClass = 3 - currentClass;
			tr.classList.add("tr1");
		}
		else {
			pitcherarray[i][0]='\u00A0'+pitcherarray[i][0];
			tr.classList.add("tr2");
		}
		[0,4,5,6,7,8,9,10].forEach( x => {
			var td = document.createElement('td');
			td.textContent = pitcherarray[i][x];
			tr.appendChild(td);
		});
		tr.addEventListener('click', e => {alert(e.target.parentNode.id);});
		
		if (pitcherarray[i][1]==0) {
			tr.id = 'offbox_A-'+i;
			tbodya.appendChild(tr);
		}
		else {
			tr.id = 'offbox_H-'+i;
			tbodyh.appendChild(tr);
		}
	}
  }
  
	
  
}

customElements.define('box-score', BoxScore);


