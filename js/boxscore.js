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
            document.getElementById("id-of-element").innerHTML = jsonFile.responseText;
        }
     }
	let template = document.getElementById('boxscore');
    let templateContent = template.content;

    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
    
    this.linescore([['A',0,0,0,0,0],['B',1,0,1,0,0]]);
    this.offbox([[['Name1',0,0,0,0,0,0,0],['Name2',0,0,0,0,0,0,0]],[['Name3',0,0,0,0,0,0,0],['Name4',0,0,0,0,0,0,0]]]);
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
	for (var i=0;i<batterarray[0].length;i++){
		var tr = document.createElement('tr');
			batterarray[0][i].forEach( x => {
				var td = document.createElement('td');
				td.textContent = x;
				tr.appendChild(td);
			});
		tr.id = 'offbox_A-'+i;
		tr.addEventListener('click', e => {alert(e.target.parentNode.id);});
		tbodya.appendChild(tr);
	}
  	for (var i=0;i<batterarray[1].length;i++){
		var tr = document.createElement('tr');
			batterarray[1][i].forEach( x => {
				var td = document.createElement('td');
				td.textContent = x;
				tr.appendChild(td);
			});
		tr.id = 'offbox_H-'+i;
		tr.addEventListener('click', e => {alert(e.target.parentNode.id);});
		tbodyh.appendChild(tr);
	}
  }
  
	
  
}

customElements.define('box-score', BoxScore);


