// Simple test to verify localStorage functionality
// Run in browser console

// Test 1: Clear any existing data
localStorage.removeItem('trading-watchlist');
console.log('Cleared existing data');

// Test 2: Add some test data
const testData = ['AAPL', 'GOOGL', 'MSFT'];
localStorage.setItem('trading-watchlist', JSON.stringify(testData));
console.log('Set test data:', testData);

// Test 3: Retrieve data
const retrieved = localStorage.getItem('trading-watchlist');
console.log('Retrieved raw data:', retrieved);

// Test 4: Parse data
const parsed = JSON.parse(retrieved);
console.log('Parsed data:', parsed);

// Test 5: Verify it's an array
console.log('Is array:', Array.isArray(parsed));

// Test 6: Simulate page refresh by getting data again
const afterRefresh = localStorage.getItem('trading-watchlist');
console.log('After refresh simulation:', JSON.parse(afterRefresh));