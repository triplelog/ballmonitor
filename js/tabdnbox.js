
class TabDNBox extends TabDN {

	constructor() {
		super();    
	
		var _this = this;
	}
	
	addData(retmess) {
		var boxes = document.querySelectorAll('box-score');
		var i = 0;
		for (var ii=0;ii*2 + 1<retmess[0].length;ii++) {
			this.colInfo[parseInt(retmess[0][ii*2 + 1])]=retmess[0][ii*2];
		}
		for (var ii=1;ii<retmess.length;ii++) {
			if (boxes.length > ii - 1){
				boxes[ii-1].setAttribute("src",retmess[ii][2]);
				boxes[ii-1].chgsrc();
			}
			else {
				var box = document.createElement('box-score');
				box.setAttribute("src",retmess[ii][2]);
				box.chgsrc();
				this.parentNode.appendChild(box);
			}
		}

  	}
	
	
}

customElements.define('tabdn-box', TabDNBox);

function after10(lks,ntel) {
	ntel.moveHeader(lks);
}

function makePost(infixexpr) {
	prec = {}
	prec["*"] = 4
	prec["/"] = 4
	prec["+"] = 3
	prec["~"] = 3
	prec[">"] = 2
	prec["<"] = 2
	prec["="] = 2
	prec["!"] = 2
	prec["["] = 2
	prec["]"] = 2
	prec["&"] = 1
	prec["|"] = 0
	prec["("] = -1
	opStack = []
	postfixList = []
	intstr = ''
	expstr = ''
	tokenList = []
	temptoken = ''
	for (var i=0;i<infixexpr.length;i++){
		var ie = infixexpr[i];
		if ("-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_.".indexOf(ie) > -1){
			temptoken += ie
		}
		else{
			if (temptoken != ''){
				tokenList.push(temptoken)
			}
			tokenList.push(ie)
			temptoken = ''
		}
	}
	if (temptoken != ''){
		tokenList.push(temptoken)
	}
	
	for (var i=0;i<tokenList.length;i++){
		var token = tokenList[i];
		if ("*/+~><=![]&|()".indexOf(token) == -1){
			postfixList.push(token)
		}
		else if (token == '('){
			opStack.push(token)
		}
		else if (token == ')'){
			topToken = opStack.pop()
			while (topToken != '('){
				postfixList.push(topToken)
				topToken = opStack.pop()
			}
		}
		else {
			while ((opStack.length > 0) && (prec[opStack[opStack.length-1]] >= prec[token])){
				postfixList.push(opStack.pop())
			}
			opStack.push(token)
		}
	}
	while (opStack.length > 0){
		postfixList.push(opStack.pop())
	}
	for (var i=0;i<postfixList.length;i++){
		var ci = postfixList[i];
		if ("*/+~><=![]&|".indexOf(ci) == -1){
			intstr += ci + ','
			expstr += '#'
		}
		else if (ci == '~'){
			expstr += '-'
		}
		else{
			expstr += ci
		}
	}
	intstr = intstr.substring(0,intstr.length-1)
	return [intstr,expstr]

}



function replaceDecimals(istr){
	dindex = istr.indexOf('.');
	while (dindex >-1){
		intpart = 0;
		decpart = 0;
		denom = 1;
		strparts = [dindex,dindex+1];
		for (var i=1;i<dindex+1;i++){
			if ("0123456789".indexOf(istr[dindex-i]) > -1){
				intpart += parseInt(istr[dindex-i])*Math.pow(10,i-1);
				strparts[0] = dindex-i;
			}
			else{break;}
		}
		for (var i=dindex+1;i<istr.length;i++){
			if ("0123456789".indexOf(istr[i]) > -1){
				decpart *=10;
				denom *=10;
				decpart += parseInt(istr[i]);
				strparts[1] = i+1;
			}
			else{break;}
		}
		istr = istr.substring(0,strparts[0])+'('+ (intpart*denom+decpart) +'/'+ denom +')'+istr.substring(strparts[1],);
		dindex = istr.indexOf('.');
	}

	return istr
}

function replaceNegatives(istr){
	dindex = istr.indexOf('-')
	while (dindex >-1){
		if (dindex == 0){
			if ("0123456789".indexOf(istr[1]) == -1) {
				istr = '-1*'+istr.substring(1,);
			}
			dindex = istr.indexOf('-',1);
		}
		else{
			if ("><=![]&|(".indexOf(istr[dindex-1])> -1) {
				if ("0123456789".indexOf(istr[dindex-1])== -1){
					istr = istr.substring(0,dindex)+'-1*'+istr.substring(dindex+1,);
				}
				dindex = istr.indexOf('-',dindex+1);
			}
			else{
				istr = istr.substring(0,dindex)+'~'+istr.substring(dindex+1,);
				dindex = istr.indexOf('-',dindex+1);
			}
		}
	}
				
	return istr
}

function replaceDates(istr){
	for (var i=0;i<istr.length-3;i++) {
		if (istr[i] == '/'){
			if (istr[i+3]=='/'){
				if (parseInt(istr.substring(i+1,i+3)) > 0 && parseInt(istr.substring(i+1,i+3)) < 33 && parseInt(istr.substring(i+1,i+3)).toString() == istr.substring(i+1,i+3)){istr[i]='.'; istr[i+3]='.';}
			}
			else if (istr[i+2]=='/'){
				if (parseInt(istr.substring(i+1,i+2)).toString() == istr.substring(i+1,i+2)){istr[i]='.'; istr[i+2]='.';}
			}
		}
	}
	return istr;
}

function postfixify(input_str,colInfo) {
	input_str = input_str.toUpperCase();
	input_str = input_str.replace(/\sAND\s/g,'&');
	input_str = input_str.replace(/\sOR\s/g,'|');
	input_str = input_str.replace(/\s/g,'');
	input_str = input_str.replace(/\[/g,'(');
	input_str = input_str.replace(/]/g,')');
	input_str = input_str.replace(/{/g,'(');
	input_str = input_str.replace(/}/g,')');
	input_str = input_str.replace(/>=/g,']');
	input_str = input_str.replace(/<=/g,'[');
	input_str = input_str.replace(/==/g,'=');
	input_str = input_str.replace(/!=/g,'!');
	input_str = input_str.replace(/\+-/g,'-');
	input_str = input_str.replace(/--/g,'+');
	//input_str = replaceDecimals(input_str);
	input_str = replaceNegatives(input_str);
	input_str = replaceDates(input_str);
	var twoparts = makePost(input_str);
	//Convert column names
	console.log(twoparts[0]);
	console.log(twoparts[1]);
	var firstpart = twoparts[0].split(",");
	for (var i=0;i<firstpart.length;i++){
		if (parseInt(firstpart[i]).toString() != firstpart[i]){
			var isColumn = false;
			for (var ii in colInfo) {
				if (colInfo[ii].toUpperCase() == firstpart[i]) {
					firstpart[i] = 'c'+ii;
					isColumn = true;
					break;
				}
			}
			if (!isColumn){
				if ( (firstpart[i].match(/\./g) || []).length > 1) {firstpart[i] = firstpart[i].replace(/\./g,'/')};
			}
		}
		else {
			firstpart[i] = firstpart[i];
		}
	}
	var fullstr = firstpart.join("_")+'@'+twoparts[1];
	return fullstr;
}

//12.3-4.5==-2+aAND4.552!=(x-1)
