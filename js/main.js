function toggleSidebar() {
	var sidebar = document.getElementById('accordionSidebar');
	if (sidebar.classList.contains('toggled')) {
		sidebar.classList.remove("toggled");
	}
	else {
		sidebar.classList.add("toggled");
	}
}

function toggleNavbar() {
	var sidebar = document.getElementById('topNavbar');
	if (sidebar.style.display != 'none') {
		sidebar.style.display = 'none';
	}
	else {
		sidebar.style.display = 'flex';
	}
}

function togglePlayers() {
	toToggle = document.getElementById('collapsePlayers');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleStreaks() {
	toToggle = document.getElementById('collapseStreaks');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleBoxes() {
	toToggle = document.getElementById('collapseBoxes');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleMaps() {
	toToggle = document.getElementById('collapseMaps');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleTeams() {
	toToggle = document.getElementById('collapseTeams');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleLeaders() {
	toToggle = document.getElementById('collapseLeaders');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleBars() {
	toToggle = document.getElementById('collapseBars');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function toggleStandings() {
	toToggle = document.getElementById('collapseStandings');
	if (toToggle.style.display != 'inline-block') {
		toToggle.style.display = 'inline-block';
	}
	else {
		toToggle.style.display = 'none';
	}
}

function computeStat(data,stat,borp='pitching') {
	var statVal = 0;
	if (stat == 'OBP'){
		statVal = (parseInt(data.H)+parseInt(data.BB)+parseInt(data.HBP))/(parseInt(data.AB)+parseInt(data.BB)+parseInt(data.HBP)+parseInt(data.SF));
	}
	else if (stat == 'SLG'){
		statVal = (parseInt(data['1B'])+2*parseInt(data['2B'])+3*parseInt(data['3B'])+4*parseInt(data.HR))/(parseInt(data.AB));
	}
	else if (stat == 'OPS'){
		statVal = computeStat(data,'OBP')+computeStat(data,'SLG');
	}
	else if (stat == 'AVG'){
		statVal = (parseInt(data.H))/(parseInt(data.AB));
	}
	else if (stat == 'ERA'){
		statVal = (parseInt(data.ER)*27)/(parseInt(data.IPouts));
	}
	else if (stat == 'FIP'){
		statVal = (parseInt(data.HR)*13+parseInt(data.BB)*3+parseInt(data.HBP)*3-2*parseInt(data.K))*3/(parseInt(data.IPouts)) + 3.2;
	}
	else if (borp == 'pitching'){
		statVal = computeCustomPitchingStat(data,stat);
	}
	else {
		statVal = computeCustomBattingStat(data,stat);
	}
	
	if (!isNaN(statVal)){
		return statVal;
	}
	else {
		return 0;
	}
}




function displayStat(stat,ndigits) {
	if (ndigits) {
		if (stat>= 1) {
			return stat.toFixed(ndigits);
		}
		else {
			return stat.toFixed(ndigits).toString().substring(1,ndigits+2);
		}
	}
	else {
		return stat;
	}
	
}
var shiohplayers = [];
var shiohteams = [];
Promise.all([d3.json("data/personJSON.json"),d3.json("data/teamsJSON.json")]).then(function(data) {
	shiohplayers = data[0];
	shiohteams = {};
	teamids = Object.keys(data[1]);
	for (var i=0;i<teamids.length;i++) {
		shiohteams[teamids[i]]={};
		teamnames = Object.keys(data[1][teamids[i]]['years']);
		
		for (var ii=0;ii<teamnames.length;ii++) {
			var teamsplit = teamnames[ii].split(' ');
			if (teamsplit.length > 3) {
				if (teamsplit[2] == 'Devil'){
					var teamloc = teamsplit[0]+' '+teamsplit[1];
					var teamnick = teamsplit[2]+' '+teamsplit[3];
				}
				if (teamsplit[3] == 'Of'){
					var teamloc = teamsplit[0]+' '+teamsplit[1];
					var teamnick = teamsplit[2];
				}
				if (teamsplit[2] == 'Brown'){
					var teamloc = teamsplit[0]+' '+teamsplit[1];
					var teamnick = teamsplit[2]+' '+teamsplit[3];
				}
			}
			else if (teamsplit.length > 2) {
				if (teamsplit[1] == 'Bay' || teamsplit[1] == 'York' || teamsplit[1] == 'Louis' || teamsplit[1] == 'City' || teamsplit[1] == 'Angeles' || teamsplit[1] == 'Francisco' || teamsplit[1] == 'Diego') {
					var teamloc = teamsplit[0]+' '+teamsplit[1];
					var teamnick = teamsplit[2];
				}
				else {
					var teamloc = teamsplit[0];
					var teamnick = teamsplit[1]+' '+teamsplit[2];
				}
				
			}
			else {
				var teamloc = teamsplit[0];
				var teamnick = teamsplit[1];
			}
			var years = data[1][teamids[i]]['years'][teamnames[ii]];
			for (var iii=0;iii<years.length;iii++) {
				shiohteams[teamids[i]][years[iii]]=[teamnames[ii],teamloc,teamnick];
			}
		}
	}
});



function computeValue(array) {
	var sumArray = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
	for (var i=yearRange[0];i<yearRange[1]+1;i++) {
		if (array[i]) {
			for (var ii=0;ii<17;ii++) {
				sumArray[ii] += array[i][ii];
			}
		}
	}

	var myFormula = mapFormula.replace(/col6/g, sumArray[6]);
	myFormula = myFormula.replace(/col0/g, sumArray[0]);
	myFormula = myFormula.replace(/col1/g, sumArray[1]);
	myFormula = myFormula.replace(/col2/g, sumArray[2]);
	myFormula = myFormula.replace(/col3/g, sumArray[3]);
	myFormula = myFormula.replace(/col4/g, sumArray[4]);
	myFormula = myFormula.replace(/col5/g, sumArray[5]);
	myFormula = myFormula.replace(/col6/g, sumArray[6]);
	myFormula = myFormula.replace(/col7/g, sumArray[7]);
	myFormula = myFormula.replace(/col8/g, sumArray[8]);
	myFormula = myFormula.replace(/col9/g, sumArray[9]);
	myFormula = myFormula.replace(/col10/g, sumArray[10]);
	myFormula = myFormula.replace(/col11/g, sumArray[11]);
	myFormula = myFormula.replace(/col12/g, sumArray[12]);
	myFormula = myFormula.replace(/col13/g, sumArray[13]);
	myFormula = myFormula.replace(/col14/g, sumArray[14]);
	myFormula = myFormula.replace(/col15/g, sumArray[15]);
	myFormula = myFormula.replace(/col16/g, sumArray[16]);
	return parseFloat(solvePolish(myFormula));
	
}

function computeCustomPitchingStat(data,formula) {

	var myFormula = toPolish(decodeFormula(formula));
	myFormula = myFormula.replace(/hr/g, data['HR']);
	
	myFormula = myFormula.replace(/ipouts/g, data['IPouts']);
	myFormula = myFormula.replace(/ip/g, data['IPouts']);
	myFormula = myFormula.replace(/er/g, data['ER']);
	myFormula = myFormula.replace(/hbp/g, data['HBP']);
	myFormula = myFormula.replace(/bb/g, data['BB']);
	myFormula = myFormula.replace(/pc/g, data['PC']);
	myFormula = myFormula.replace(/k/g, data['K']);
	myFormula = myFormula.replace(/r/g, data['R']);
	myFormula = myFormula.replace(/h/g, data['H']);

	return parseFloat(solvePolish(myFormula));
	
}

function computeCustomBattingStat(data,formula) {

	var myFormula = toPolish(decodeFormula(formula));
	myFormula = myFormula.replace(/rbi/g, data['RBI']);
	myFormula = myFormula.replace(/hbp/g, data['HBP']);
	myFormula = myFormula.replace(/hr/g, data['HR']);
	myFormula = myFormula.replace(/bb/g, data['BB']);
	myFormula = myFormula.replace(/1b/g, data['1B']);
	myFormula = myFormula.replace(/2b/g, data['2B']);
	myFormula = myFormula.replace(/3b/g, data['3B']);
	myFormula = myFormula.replace(/ab/g, data['AB']);
	myFormula = myFormula.replace(/pa/g, data['PA']);
	myFormula = myFormula.replace(/h/g, data['H']);
	myFormula = myFormula.replace(/k/g, data['K']);
	myFormula = myFormula.replace(/r/g, data['R']);

	return parseFloat(solvePolish(myFormula));
	
}



function toFormula(str) {
	str = decodeFormula(str);
	str = str.replace(/ibb/g, "col12");
	str = str.replace(/rbi/g, "col7");
	str = str.replace(/gidp/g, "col16");
	str = str.replace(/hbp/g, "col13");
	
	str = str.replace(/ab/g, "col1");
	
	str = str.replace(/2b/g, "col4");
	str = str.replace(/3b/g, "col5");
	str = str.replace(/hr/g, "col6");
	
	str = str.replace(/sb/g, "col8");
	str = str.replace(/cs/g, "col9");
	str = str.replace(/bb/g, "col10");
	str = str.replace(/so/g, "col11");
	
	
	str = str.replace(/sh/g, "col14");
	str = str.replace(/sf/g, "col15");
	
	
	str = str.replace(/g/g, "col0");
	str = str.replace(/r/g, "col2");
	str = str.replace(/h/g, "col3");
	return toPolish(str);
}

function decodeFormula(rawstr) {
	str = decodeURIComponent(rawstr).replace(/\s/g, "").toLowerCase();
	return str;
}

function toPolish(infix) {
	var outputQueue = "";
	var operatorStack = [];
	var operators = {
		"^": {
			precedence: 4,
			associativity: "Right"
		},
		"/": {
			precedence: 3,
			associativity: "Left"
		},
		"*": {
			precedence: 3,
			associativity: "Left"
		},
		"+": {
			precedence: 2,
			associativity: "Left"
		},
		"-": {
			precedence: 2,
			associativity: "Left"
		}
	}
	infix = infix.replace(/\s+/g, "");
	infix = clean(infix.split(/([\+\-\*\/\^\(\)])/));
	for(var i = 0; i < infix.length; i++) {
		var token = infix[i];
		if(isNumericCol(token)) {
			outputQueue += token + " ";
		} else if("^*/+-".indexOf(token) !== -1) {
			var o1 = token;
			var o2 = operatorStack[operatorStack.length - 1];
			while("^*/+-".indexOf(o2) !== -1 && ((operators[o1].associativity === "Left" && operators[o1].precedence <= operators[o2].precedence) || (operators[o1].associativity === "Right" && operators[o1].precedence < operators[o2].precedence))) {
				outputQueue += operatorStack.pop() + " ";
				o2 = operatorStack[operatorStack.length - 1];
			}
			operatorStack.push(o1);
		} else if(token === "(") {
			operatorStack.push(token);
		} else if(token === ")") {
			while(operatorStack[operatorStack.length - 1] !== "(") {
				outputQueue += operatorStack.pop() + " ";
			}
			operatorStack.pop();
		}
	}
	while(operatorStack.length > 0) {
		outputQueue += operatorStack.pop() + " ";
	}
	return outputQueue;
}

function clean(array) {
	for(var i = 0; i < array.length; i++) {
        if(array[i] === "") {
            array.splice(i, 1);
        }
    }
    return array;
}

function isNumeric(str) {
	return !isNaN(parseFloat(str)) && isFinite(str);
}

function isNumericCol(str) {

	if (str == 'pa' || str == 'ab' || str == 'rbi' || str == '1b' || str == '2b' || str == '3b' || str == 'ip' || str == 'ipouts' || str == 'h' || str == 'bb' || str == 'r' || str == 'er' || str == 'pc' || str == 'k' || str == 'hr' || str == 'hbp') {
		return true;
	}
	else if (str.substring(0,3) == 'col') {
		return !isNaN(parseFloat(str.substring(3,str.length))) && isFinite(str.substring(3,str.length));
	}
	else {
		return !isNaN(parseFloat(str)) && isFinite(str);
	}
}

function solvePolish(postfix) {
	var resultStack = [];
	postfix = clean(postfix.split(" "));
	for(var i = 0; i < postfix.length; i++) {
		if(isNumeric(postfix[i])) {
			resultStack.push(postfix[i]);
		} else {
			var a = resultStack.pop();
			var b = resultStack.pop();
			if(postfix[i] === "+") {
				resultStack.push(parseFloat(a) + parseFloat(b));
			} else if(postfix[i] === "-") {
				resultStack.push(parseFloat(b) - parseFloat(a));
			} else if(postfix[i] === "*") {
				resultStack.push(parseFloat(a) * parseFloat(b));
			} else if(postfix[i] === "/") {
				resultStack.push(parseFloat(b) / parseFloat(a));
			} else if(postfix[i] === "^") {
				resultStack.push(Math.pow(parseFloat(b), parseFloat(a)));
			}
		}
	}
	if(resultStack.length > 1) {
		return "error";
	} else {
		return resultStack.pop();
	}
}