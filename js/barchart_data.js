var myData = [];
var data = {};
var firstYear = 0;
var newYear = firstYear;
var yearInterval;
var nLeaders = 10;

var allY;

var svg;

function loadRace() {
	d3.csv("fn.csv").then(function(rawData) {
		for (var i=0;i<rawData.length;i++) {
			maxII = i-(i%10);
			if (i%10 == 0){data[rawData[i]['Split']]=[];}
			lastRank = 11;
			if (parseInt(rawData[i]['Split']) >= 1) {
				for (var ii=0;ii<10;ii++) {
					if (data[parseInt(rawData[i]['Split'])-1][ii]['id'] == rawData[i]['PID']) {
						lastRank = ii+1;
						break;
					}
				}
			}
			thisRow = {'id':rawData[i]['PID'],'war':rawData[i]['N'],'rank':(i%10)+1,'last':lastRank,'lastwar':rawData[i]['LN']};
			
			data[rawData[i]['Split']].push(thisRow);
		}
		allY = [];
		for (var i=0;i<nLeaders + 1;i++) {
			allY.push(nLeaders + 1 - i);
		}
		//console.log(allY);
		createRace();
	});

}

function createRace(){
		
	// set the dimensions and margins of the graph
	var margin = {top: 20, right: 20, bottom: 30, left: 40},
    width = 960 - margin.left - margin.right,
    height = 500 - margin.top - margin.bottom;

	svg = d3.select("#barchart-location")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", 
          "translate(" + margin.left + "," + margin.top + ")");
          
	// set the ranges
	var y = d3.scaleBand()
          .range([height, 0])
          .padding(0.1);

	var x = d3.scaleLinear()
          .range([0, width]);
          
	// append the svg object to the body of the page
	// append a 'group' element to 'svg'
	// moves the 'group' element to the top left margin


  // format the data
  data[firstYear].forEach(function(d) {
    d.war = +d.war;
  });

  // Scale the range of the data in the domains
  x.domain([0, d3.max(data[199], function(d){ return d.war; })])
  y.domain(allY);
  //y.domain([0, d3.max(data, function(d) { return d.sales; })]);

  // append the rectangles for the bar chart
  svg.selectAll(".bar")
      .data(data[firstYear])
    .enter().append("rect")
      .attr("class", "bar")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("width", function(d) {return x(d.war); } )
      .attr("y", function(d) { return y(d.rank); })
      .attr("height", y.bandwidth());

  svg.selectAll(".barText")
      .data(data[firstYear])
    .enter().append("text")
      .attr("class", "barText")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("y", function(d) { return y(d.rank) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.war); })
      .attr("height", y.bandwidth())
      .text(function(d) { return d.id; });

  // add the x Axis
  svg.append("g")
  	  .attr('id','xAxis')
      .attr("transform", "translate(0," + height + ")")
      .call(d3.axisBottom(x));

  // add the y Axis
  svg.append("g")
  	 .attr('id','yAxis')
      .call(d3.axisLeft(y));
	
    
	
}


function pressButton() {
	yearInterval = setInterval(function(){ updateRace(500); }, 600);
}
function updateRace(duration) {
	
	newYear += 1;
	if (newYear >= 199){
		clearInterval(yearInterval);
		
	}

	
	var margin = {top: 20, right: 20, bottom: 30, left: 40},
    width = 960 - margin.left - margin.right,
    height = 500 - margin.top - margin.bottom;
  // format the data
  data[newYear].forEach(function(d) {
    d.war = +d.war;
  });
  
	// set the ranges
	var y = d3.scaleBand()
          .range([height, 0])
          .padding(0.1);

	var x = d3.scaleLinear()
          .range([0, width]);
	// Scale the range of the data in the domains
  x.domain([0, d3.max(data[199], function(d){ return d.war; })])
  y.domain( allY );
  //y.domain([0, d3.max(data, function(d) { return d.sales; })]);
  
  svg.selectAll(".bar")
      .data(data[newYear])
    .enter().append("rect")
      .attr("class", "bar")
      //.attr("x", function(d) { return x(d.sales); })
      .attr("width", function(d) {return 0; } )
      .attr("y", function(d) { return y.bandwidth(); })
      .attr("height", y.bandwidth());
      
  svg.selectAll(".bar")
      .data(data[newYear])
    .exit().remove();

	svg.selectAll(".barText")
      .data(data[newYear])
    .exit().remove();
    
	svg.selectAll(".barText")
      .data(data[newYear])
    .enter().append("text")
      .attr("class", "barText");
      
  svg.selectAll(".barText")
      .data(data[newYear])
    .exit().remove();
      
  // append the rectangles for the bar chart
  svg.selectAll("rect")
      .data(data[newYear])
      .attr("width", function(d) {return x(d.lastwar); } )
      .attr("y", function(d) { if (d.id == "Ken Griffey") {console.log(d)}; return y(d.last); })
      .transition()
      .duration(duration)
      .attr("width", function(d) {return x(d.war); } )
      .attr("y", function(d) { return y(d.rank); });
  
  svg.selectAll("text")
      .data(data[newYear])
      .attr("y", function(d) { return y(d.last) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.lastwar); })
      .attr("height", y.bandwidth())
      .text(function(d) { return d.id; })
      .transition()
      .duration(duration)
      .attr("y", function(d) { return y(d.rank) + y.bandwidth()/2 + 6; })
      .attr("x", function(d) { return x(d.war); })
      .attr("height", y.bandwidth())
      
      

	var yAxis = d3.select("#xAxis")
      .call(d3.axisBottom(x));
  // add the y Axis
  var yAxis = d3.select("#yAxis")
      .call(d3.axisLeft(y));
}







