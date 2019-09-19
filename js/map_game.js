
    	

function updateSlider(value) {
	addGame(value);
}



var states = {'SC':[],'NC':[],'GA':[],'TN':[],'VA':[],'AL':[],'FL':[],'KY':[],'MS':[],'LA':[]};
var stateList = Object.keys(states);
var statsVisible = [true,false];


			   
function createMap(){
	
	var mapSVG = document.getElementById('mapSVG');
	var mapWidth = document.getElementById('map').offsetWidth - 30;
	mapSVG.setAttribute("width", mapWidth+"px");
	mapSVG.setAttribute("height", parseInt(mapWidth*750/1350)+"px");
    for (var i=0;i<10;i++){
    	stateid = 'state'+stateList[i];
    	if (i<5) {
    		document.getElementById(stateid).style.fill = 'green';
    	}
    	else {
    		document.getElementById(stateid).style.fill = 'orange';
    	}
    }
						
	
}

function chgStats(statid) {
	//update D3 with stat profile
	
	//update
	var thisStat = document.getElementById('stat'+statid);
	if (statsVisible[statid]) {
		thisStat.classList.remove('btn-primary');
		thisStat.classList.add('disabled');
		thisStat.classList.add('btn-secondary');
		statsVisible[statid]=false;
	}
	else {
		thisStat.classList.remove('btn-secondary');
		thisStat.classList.remove('disabled');
		thisStat.classList.add('btn-primary');
		statsVisible[statid]=true;
	}
	console.log(statid);
}

function clickstate(stateid) {
	document.getElementById(stateid).style.fill = 'red';
}

function toggleMapSidebar() {
	toggleSidebar();
	createMap();
	toggleNavbar();
}






