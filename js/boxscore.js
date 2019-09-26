class BoxScore extends HTMLElement {
  

  constructor() {
    super();    
    
	
	var _this = this;
	
	let template = document.getElementById('boxscore');
    let templateContent = template.content;
    
    const shadowRoot = this.attachShadow({mode: 'open'}).appendChild(templateContent.cloneNode(true));
    this.style.display = 'none';
    this.chgsrc();

	

  }
  
  chgsrc() {
  	var _this = this;
    this.gameid = this.getAttribute('src');
    if (this.gameid == null) {return 0;}
    else {this.style.display = 'block';}
  	var url = 'box/2000/2000'+this.gameid.substring(0,3)+'/'+this.gameid+'batterbox.csv';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();

    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            _this.offbox(Papa.parse(jsonFile.responseText).data);
        }
     }
    var url2 = 'box/2000/2000'+this.gameid.substring(0,3)+'/'+this.gameid+'pitcherbox.csv';
	var jsonFile2 = new XMLHttpRequest();
    jsonFile2.open("GET",url2,true);
    jsonFile2.send();
	jsonFile2.onloadend = function() {
		if(jsonFile2.status == 404) {
			this.style.display = 'none';
		}
		else if (jsonFile2.status == 200) {
            _this.pitchbox(Papa.parse(jsonFile2.responseText).data);
        }
	}

    
    var url4 = 'box/2000/2000'+this.gameid.substring(0,3)+'/'+this.gameid+'.txt';
	var jsonFile4 = new XMLHttpRequest();
    jsonFile4.open("GET",url4,true);
    jsonFile4.send();

    jsonFile4.onreadystatechange = function() {
        if (jsonFile4.readyState== 4 && jsonFile4.status == 200) {
            _this.linescore(Papa.parse(jsonFile4.responseText).data);
        }
     }
     
     
     
	
  }
  
  linescore(gameinfo) {
  	var _this = this;
  	var awayteam = "Away";
	var hometeam = "Home";
  	for (var i=0;i<gameinfo.length;i++){
  		if (gameinfo[i][1] == 'visteam') {awayteam = gameinfo[i][2];}
  		else if (gameinfo[i][1] == 'hometeam') {hometeam = gameinfo[i][2];}
  	}
  	
  	var url = 'box/2000/2000'+this.gameid.substring(0,3)+'/'+this.gameid+'plays.csv';
	var jsonFile = new XMLHttpRequest();
    jsonFile.open("GET",url,true);
    jsonFile.send();
	
    jsonFile.onreadystatechange = function() {
        if (jsonFile.readyState== 4 && jsonFile.status == 200) {
            var linescoreRaw = Papa.parse(jsonFile.responseText).data;
            var linescore = _this.shadowRoot.querySelector('#linescore-location');
			var thead = linescore.querySelector('thead').querySelector('tr');
			var row1 = linescore.querySelector('tbody').querySelectorAll('tr')[0];
			var row2 = linescore.querySelector('tbody').querySelectorAll('tr')[1];
			thead.innerHTML = '';
			row1.innerHTML = '';
			row2.innerHTML = '';
	
			
			var pbpLength = linescoreRaw.length;
			  var linescorearray = [[awayteam],[hometeam]];
			  console.log(linescorearray);
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
     }
  	
  	
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
	console.log(pitcherarray);
	
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


