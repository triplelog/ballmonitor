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
  	var offboxa = this.shadowRoot.querySelector('#stats-location');
  	var theada = offboxa.querySelector('thead').querySelector('tr');
  	var tbodya = offboxa.querySelector('tbody');
  	theada.innerHTML = '';
  	tbodya.innerHTML = '';
  	['Name','PA','AB','H','BB','R','RBI','K'].forEach(x => {
  		var th = document.createElement('th');
		th.textContent = x;
		theada.appendChild(th);
	});
	console.log(statarray);
	
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
		[4,5,6,7,8,9,10].forEach( x => {
			if (statarray[i][27]==0) {
				years[year][ii] += parseInt(statarray[i][x]);
				years.total[ii] += parseInt(statarray[i][x]);
			}
			ii++;
		});

	}
	for(year in years){
		if (year == 'total'){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		var td = document.createElement('td');
		td.textContent = year;
		tr.appendChild(td);
		[0,1,2,3,4,5,6].forEach( x => {
			td = document.createElement('td');
			td.textContent = years[year][x];
			tr.appendChild(td);
		});
		

		tbodya.appendChild(tr);
	}
	var tr = document.createElement('tr');
	tr.classList.add("tr1");
	var td = document.createElement('td');
	td.textContent = 'Total';
	tr.appendChild(td);
	[0,1,2,3,4,5,6].forEach( x => {
		td = document.createElement('td');
		td.textContent = years.total[x];
		tr.appendChild(td);
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
		console.log(this.colInfo);
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

