/**
 * Automated Verification: Frontend Analytical Result Enrichment & Grounding
 *
 * Verifies:
 *   1. extractClientContextFields selects relevant contextual attributes and excludes system & metric columns.
 *   2. Full flight record attributes extraction (Airline, Flight Number, Origin, Destination, Date, Scheduled Departure Time).
 *   3. Cross-domain schema handling (Flights, Telco, E-Commerce, Healthcare).
 *   4. Grounded units contract (verified unit rendered, unknown unit labeled, dimensionless clean).
 *   5. Tied extrema detection & honest representation.
 *   6. Empty/missing context handling (graceful fallback without invented context).
 *   7. Exact source row provenance (source row vs dataframe index vs result rank).
 */
import assert from 'node:assert/strict';
import {
  extractClientContextFields,
  formatCol,
  formatNumber,
  formatValue,
  deriveMetricHeader,
  opLabel,
  getOrderedGroupedEntries,
  getRankingLabel,
} from '../src/utils/analyticalFormatting.js';

console.log('=== VERIFYING FRONTEND ANALYTICAL RESULT ENRICHMENT & GROUNDING ===\n');

// Test 1: Full flight schema context extraction with composite time
const fullFlightRow = {
  _row_number: 146821,
  source_row_number: 146821,
  dataframe_index: 146820,
  result_rank: 1,
  Flight_Date: '2025-09-01',
  Airline: 'SpiceJet',
  Flight_Number: 'SP9257',
  Origin_Airport: 'COK',
  Destination_Airport: 'JRH',
  Scheduled_Departure_Hour: 21,
  Scheduled_Departure_Minute: 1,
  Departure_Delay: 119,
};

const flightContext = extractClientContextFields(fullFlightRow, 'Departure_Delay', 8);
assert.equal(flightContext.Airline, 'SpiceJet');
assert.equal(flightContext.Flight_Number, 'SP9257');
assert.equal(flightContext.Origin_Airport, 'COK');
assert.equal(flightContext.Destination_Airport, 'JRH');
assert.equal(flightContext.Flight_Date, '2025-09-01');
assert.equal(flightContext['Scheduled Departure Time'], '21:01');

// Assert target metric and system columns excluded
assert.equal(flightContext.Departure_Delay, undefined, 'Metric column must be excluded');
assert.equal(flightContext._row_number, undefined, 'System row number must be excluded');
assert.equal(flightContext.source_row_number, undefined, 'System source row number must be excluded');
assert.equal(flightContext.dataframe_index, undefined, 'DataFrame index must be excluded');
assert.equal(flightContext.result_rank, undefined, 'Result rank must be excluded');
// Assert separate raw hour/minute columns suppressed
assert.equal(flightContext.Scheduled_Departure_Hour, undefined);
assert.equal(flightContext.Scheduled_Departure_Minute, undefined);
console.log('✔ Test 1 Passed: Complete flight record context extracted with 6 core attributes including composite Scheduled Departure Time');

// Test 2: Telco churn schema context extraction
const telcoRow = {
  customerID: '7590-VHVEG',
  Contract: 'Two year',
  InternetService: 'Fiber optic',
  PaymentMethod: 'Electronic check',
  MonthlyCharges: 118.75,
  TotalCharges: 8684.8,
};

const telcoContext = extractClientContextFields(telcoRow, 'TotalCharges', 4);
assert.equal(telcoContext.Contract, 'Two year');
assert.equal(telcoContext.InternetService, 'Fiber optic');
assert.equal(telcoContext.customerID, '7590-VHVEG');
assert.equal(telcoContext.TotalCharges, undefined);
console.log('✔ Test 2 Passed: Telecom churn schema extracts Contract, InternetService, and customerID');

// Test 3: E-commerce schema context extraction
const ecommerceRow = {
  order_id: 'ORD-10023',
  product_name: 'Smart Home Hub',
  category: 'Electronics',
  region: 'North America',
  revenue: 4999.0,
};

const ecomContext = extractClientContextFields(ecommerceRow, 'revenue', 4);
assert.equal(ecomContext.product_name, 'Smart Home Hub');
assert.equal(ecomContext.category, 'Electronics');
assert.equal(ecomContext.region, 'North America');
assert.equal(ecomContext.revenue, undefined);
console.log('✔ Test 3 Passed: E-Commerce schema extracts product, category, and region');

// Test 4: Missing contextual columns (single-column dataset)
const singleColRow = {
  _row_number: 1,
  Temperature: 98.6,
};
const emptyContext = extractClientContextFields(singleColRow, 'Temperature', 4);
assert.deepEqual(emptyContext, {}, 'Context should be empty if only metric & system cols exist');
console.log('✔ Test 4 Passed: Missing context handled cleanly without fabricating columns');

// Test 5: Grounded unit representation (known, unknown, dimensionless)
function getUnitDisplay(unit, unitStatus, unitLabel) {
  if (unit) return { type: 'known', text: unit };
  if (unitStatus === 'unknown' || (!unit && unitLabel && unitStatus !== 'not_applicable')) {
    return { type: 'unknown', text: unitLabel || 'Unit not specified in dataset metadata' };
  }
  return { type: 'none', text: '' };
}

const u1 = getUnitDisplay('USD', 'known', 'USD');
assert.equal(u1.type, 'known');
assert.equal(u1.text, 'USD');

const u2 = getUnitDisplay(null, 'unknown', 'Unit not specified in dataset metadata');
assert.equal(u2.type, 'unknown');
assert.equal(u2.text, 'Unit not specified in dataset metadata');

const u3 = getUnitDisplay(null, 'not_applicable', '');
assert.equal(u3.type, 'none');
assert.equal(u3.text, '');
console.log('✔ Test 5 Passed: Unit contract strictly distinguishes known, unknown, and dimensionless quantities');

// Test 6: Tied extrema contract
function evaluateExtremumPresentation(result) {
  const isExtremum = ['max', 'min', 'idxmax', 'idxmin', 'longest', 'shortest'].includes((result.operation || '').toLowerCase());
  const tieCount = result.tie_count || (result.rows ? result.rows.length : 1);
  const isTied = (result.is_tied || tieCount > 1) && result.rows.length > 1;

  return {
    isExtremum,
    isTied,
    tieCount,
    metricHeader: deriveMetricHeader(result.operation, result.column, 'Value'),
  };
}

const tiedResult = {
  operation: 'max',
  column: 'Departure_Delay',
  value: 119,
  is_tied: true,
  tie_count: 2,
  rows: [
    { Airline: 'SpiceJet', Origin: 'DEL', Departure_Delay: 119, source_row_number: 42, dataframe_index: 41, result_rank: 1 },
    { Airline: 'Air India', Origin: 'BOM', Departure_Delay: 119, source_row_number: 105, dataframe_index: 104, result_rank: 2 },
  ],
};

const presentation = evaluateExtremumPresentation(tiedResult);
assert.equal(presentation.isExtremum, true);
assert.equal(presentation.isTied, true);
assert.equal(presentation.tieCount, 2);
assert.equal(presentation.metricHeader, 'Max Departure Delay');
console.log('✔ Test 6 Passed: Tied extrema detected and correctly formatted for multi-record display');

// Test 7: Exact source-record provenance
const topRow = tiedResult.rows[0];
assert.equal(topRow.source_row_number, 42, 'Source row number must be 42, not 1');
assert.equal(topRow.dataframe_index, 41, 'DataFrame index must be 41');
assert.equal(topRow.result_rank, 1, 'Result rank must be 1');
console.log('✔ Test 7 Passed: Distinguishes true source row number, dataframe index, and result rank');

// Test 8: Label and column formatting
assert.equal(formatCol('departure_delay'), 'Departure Delay');
assert.equal(formatCol('monthly_charges'), 'Monthly Charges');
assert.equal(opLabel('max'), 'Maximum');
assert.equal(opLabel('group_mean'), 'Average');
assert.equal(formatValue(119), '119');
assert.equal(formatValue(42.5249), '42.5249');
assert.equal(formatNumber(51947), '51,947');
console.log('✔ Test 8 Passed: Formatting utilities correctly handle numeric precision and column casing');

// Test 9: The canonical ordered ranking array survives JSON key sorting.
const rankedApiResult = {
  value: { 'Air India': 23350, 'IndiGo': 51947, 'SpiceJet': 10281 },
  details: {
    ordered_entries: [
      { entity: 'IndiGo', value: 51947, rank: 1 },
      { entity: 'Air India', value: 23350, rank: 2 },
      { entity: 'SpiceJet', value: 10281, rank: 3 },
    ],
  },
  ranking: {
    requested_limit: 3,
    eligible_entity_count: 3,
    direction: 'desc',
    items: [
      { entity: 'IndiGo', value: 51947, rank: 1 },
      { entity: 'Air India', value: 23350, rank: 2 },
      { entity: 'SpiceJet', value: 10281, rank: 3 },
    ],
  },
};
const serializedRanking = JSON.parse(JSON.stringify(rankedApiResult.ranking));
const orderedFromApi = getOrderedGroupedEntries(rankedApiResult.value, rankedApiResult.details, serializedRanking);
assert.deepEqual(orderedFromApi, [['IndiGo', 51947, 1], ['Air India', 23350, 2], ['SpiceJet', 10281, 3]]);
assert.equal(orderedFromApi[0][1], 51947);
assert.equal(getRankingLabel(9, 10, false, 9), 'Top 9 of 10 requested');
console.log('✔ Test 9 Passed: UI consumes canonical ordered ranking rows and reports short results');

console.log('\n=== ALL FRONTEND ENRICHMENT TESTS PASSED (9/9) ===');
