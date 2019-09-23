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
    console.log(this);
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
	for (var i=1;i<statarray.length;i++){
		if (statarray[i].length < 10){continue;}
		var tr = document.createElement('tr');
		tr.classList.add("tr1");
		
		[0,4,5,6,7,8,9,10].forEach( x => {
			var td = document.createElement('td');
			td.textContent = statarray[i][x];
			tr.appendChild(td);
		});
		tbodya.appendChild(tr);

	}
  }
  
	
  
}

customElements.define('player-stats', PlayerStats);


