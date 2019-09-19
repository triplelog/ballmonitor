
//var statePaths = {'AL': ['path0-1', 'path2-0', 'path3-4', 'path4-2'], 'FL': ['path0-1', 'path0-30'], 'GA': ['path2-0', 'path0-30', 'path31-32', 'path32-33', 'path2-31'], 'MS': ['path3-4', 'path9-5', 'path5-60', 'path9-4'], 'TN': ['path4-2', 'path8-9', 'path2-31', 'path58-56', 'path56-8', 'path9-4', 'path31-80', 'path58-80'], 'AR': ['path5-6', 'path7-8', 'path9-5', 'path10-7', 'path8-9', 'path6-10'], 'LA': ['path5-6', 'path5-60', 'path61-6'], 'MO': ['path7-8', 'path35-38', 'path49-35', 'path54-55', 'path56-49', 'path54-38', 'path7-55', 'path56-8'], 'OK': ['path10-7', 'path19-21', 'path55-19', 'path7-55', 'path21-86', 'path10-86'], 'TX': ['path6-10', 'path61-6', 'path86-87', 'path10-86'], 'AZ': ['path11-12', 'path13-14', 'path12-15', 'path15-13'], 'CA': ['path11-12', 'path16-12', 'path17-16'], 'NM': ['path13-14', 'path21-13', 'path21-86', 'path86-87'], 'NV': ['path12-15', 'path16-12', 'path42-43', 'path16-43', 'path42-15'], 'UT': ['path15-13', 'path13-22', 'path45-42', 'path42-15', 'path45-22'], 'OR': ['path17-16', 'path43-44', 'path16-43', 'path92-44'], 'CO': ['path18-19', 'path20-18', 'path21-13', 'path19-21', 'path13-22', 'path22-20'], 'KS': ['path18-19', 'path54-55', 'path18-54', 'path55-19'], 'NE': ['path20-18', 'path38-39', 'path18-54', 'path54-38', 'path82-39', 'path20-82'], 'WY': ['path22-20', 'path41-45', 'path78-41', 'path20-82', 'path82-78', 'path45-22'], 'CT': ['path23-24', 'path25-23', 'path24-26'], 'MA': ['path23-24', 'path62-63', 'path23-64', 'path65-24', 'path64-62'], 'NY': ['path25-23', 'path23-64', 'path84-25', 'path84-88', 'path89-64'], 'RI': ['path24-26', 'path65-24'], 'DE': ['path27-28', 'path28-29'], 'MD': ['path27-28', 'path66-28', 'path67-67', 'path68-66'], 'PA': ['path28-29', 'path66-28', 'path85-84', 'path84-88', 'path90-91', 'path66-91'], 'NC': ['path31-32', 'path79-32', 'path31-80', 'path80-81'], 'SC': ['path32-33', 'path79-32'], 'IA': ['path34-35', 'path36-37', 'path35-38', 'path38-39', 'path39-36', 'path37-34'], 'IL': ['path34-35', 'path47-48', 'path48-49', 'path49-35', 'path34-50'], 'MN': ['path36-37', 'path73-74', 'path36-73', 'path75-37'], 'SD': ['path39-36', 'path36-73', 'path77-78', 'path73-77', 'path82-39', 'path82-78'], 'WI': ['path37-34', 'path34-50', 'path71-72', 'path75-37'], 'ID': ['path40-41', 'path42-43', 'path43-44', 'path45-42', 'path44-46', 'path41-45'], 'MT': ['path40-41', 'path76-77', 'path77-78', 'path78-41'], 'WA': ['path44-46', 'path92-44'], 'IN': ['path47-48', 'path51-48', 'path52-53', 'path53-51'], 'KY': ['path48-49', 'path51-48', 'path56-49', 'path51-57', 'path58-56', 'path59-58', 'path57-59'], 'MI': ['path52-53', 'path70-53', 'path71-72'], 'OH': ['path53-51', 'path51-57', 'path70-53', 'path90-91', 'path91-57'], 'VA': ['path59-58', 'path67-67', 'path80-81', 'path58-80', 'path59-68'], 'WV': ['path57-59', 'path68-66', 'path91-57', 'path66-91', 'path59-68'], 'NH': ['path62-63', 'path63-69', 'path62-83'], 'VT': ['path64-62', 'path62-83', 'path89-64'], 'ME': ['path63-69'], 'ND': ['path73-74', 'path76-77', 'path73-77'], 'NJ': ['path84-25', 'path85-84']};

var stateData = {};

var mapFormula = toFormula(window.location.search.substring(9));
console.log(mapFormula);

var yearRange = [1900,1905]
var colorSlider;
var pipvalues = [1,2,3,4,5,6,7,8];


d3.json("python/stateYears.json").then(function(data) {
  stateData = data;
  updateMap();
  
  
  
});

function updateMapFormula() {
	mapFormula = toFormula(document.getElementById('scoreFormula').value);
	updateMap();
}

function updateMap() {
	
	var states = Object.keys(stateData);
  var maxValue = 0;
  var stateAmts = {};
  var exponent = .25;
  
  for (var i=0;i<states.length;i++) {
  		if (states[i] == 'F' || states[i] == 'AK' || states[i] == 'HI' || states[i] == 'DC') {continue}
  		
  		
  		stateAmts[states[i]] = computeValue(stateData[states[i]]);
  		if (stateAmts[states[i]] > maxValue) {
  			maxValue = stateAmts[states[i]];
  		}
  }
  	var valueRanges = [0];
	var connect = colorSlider.querySelectorAll('.noUi-connect');

	for (var i = 0; i < connect.length; i++) {
		connect[i].style.backgroundColor = colorMaps['Blues']['colors'][i];
		valueRanges.push(parseInt(Math.pow(pipvalues[i]*Math.pow(maxValue,exponent)/9,1/exponent)));
	}	
	console.log(valueRanges);
	
	colorSlider.noUiSlider.pips( { mode: 'values',
			values: pipvalues,
			density: 0,
			format: {
				to: function (value) {
					return parseInt(Math.pow(value*Math.pow(maxValue,exponent)/9,1/exponent));
				}
			}
		});
		
  for (var i=0;i<states.length;i++) {
  		if (states[i] == 'F' || states[i] == 'AK' || states[i] == 'HI' || states[i] == 'DC') {continue}
  		
  		var stateSVG = document.getElementById('state'+states[i]);
  		
  		
  		for (var ii=0;ii<9;ii++) {
  			if (ii==8){
  				var myColor = colorMaps['Blues']['colors'][ii];
				stateSVG.setAttribute('fill',myColor);
  			}
  			else if (stateAmts[states[i]]<valueRanges[ii+1]) {
				var myColor = colorMaps['Blues']['colors'][ii];
				stateSVG.setAttribute('fill',myColor);
				break;
			}
  		}
  }
  
  
    
  
   
}






			   
function createMap(){
	
	
	
	var mapSVG = document.getElementById('mapSVG');
	var mapWidth = document.getElementById('map').offsetWidth - 30;
	mapSVG.setAttribute("width", mapWidth+"px");
	mapSVG.setAttribute("height", parseInt(mapWidth*750/1350)+"px");
    
	colorSlider = document.getElementById('colorSlider');

	noUiSlider.create(colorSlider, {
		start: [1,2,3,4,5,6,7,8],
		connect: [true, true, true, true, true, true, true, true, true],
		orientation: "horizontal",
		pips: {
			mode: 'values',
			values: [1,2,3,4,5,6,7,8],
			density: 0,
			format: {
				// 'to' the formatted value. Receives a number.
				to: function (value) {
					return parseInt(value);
				}
			}
		},
		range: {
			'min': [0],
			'max': [9]
		}
	});
    var connect = colorSlider.querySelectorAll('.noUi-connect');

	for (var i = 0; i < connect.length; i++) {
		connect[i].style.backgroundColor = colorMaps['Blues']['colors'][i];
		console.log(colorMaps['Blues']['colors'][i]);
	}	
	
	var slider2 = document.getElementById('yearSlider');

	noUiSlider.create(slider2, {
		start: [1900,2018],
		orientation: "horizontal",
		pips: {
			mode: 'values',
			values: [1900,1920,1940,1960,1980,2000,2018],
			density: 3
		},
		step: 1,
		behaviour: 'drag',
		connect: true,
		range: {
			'min': [1900],
			'max': [2018]
		}
	});
	
	slider2.noUiSlider.on('update', function (values) { 
		yearRange[1] = values[1];
		yearRange[0] = values[0];
		updateMap();
	});
	
	colorSlider.noUiSlider.on('update', function (values) { 
		pipvalues[0] = parseFloat(values[0]);
		pipvalues[1] = parseFloat(values[1]);
		pipvalues[2] = parseFloat(values[2]);
		pipvalues[3] = parseFloat(values[3]);
		pipvalues[4] = parseFloat(values[4]);
		pipvalues[5] = parseFloat(values[5]);
		pipvalues[6] = parseFloat(values[6]);
		pipvalues[7] = parseFloat(values[7]);
		pipvalues[8] = parseFloat(values[8]);
		updateMap();
	});
    	
	
}


function clickstate(stateid) {
	//document.getElementById(stateid).style.fill = 'red';
}







