// Buylist JavaScript - All the Interactive Magic! ✨

// Configuration
const API_URL = 'http://localhost:5001/api';

// State Management
let cart = [];
let searchResults = [];

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    updateCartDisplay();
});

// Setup all button clicks and events
function setupEventListeners() {
    // Search button
    document.getElementById('searchButton').addEventListener('click', searchCards);
    
    // Enter key in search box
    document.getElementById('searchInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') searchCards();
    });
    
    // Payout method change
    document.querySelectorAll('input[name="payout"]').forEach(radio => {
        radio.addEventListener('change', updateTotal);
    });
    
    // Submit button
    document.getElementById('submitButton').addEventListener('click', submitBuylist);
}

// Search for cards
async function searchCards() {
    const query = document.getElementById('searchInput').value.trim();
    
    if (!query || query.length < 2) {
        alert('Please enter at least 2 characters');
        return;
    }
    
    const resultsDiv = document.getElementById('searchResults');
    resultsDiv.innerHTML = '<p class="loading">Searching...</p>';
    
    try {
        const response = await fetch(`${API_URL}/cards/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        
        if (data.success && data.results.length > 0) {
            searchResults = data.results;
            displaySearchResults(data.results);
        } else {
            resultsDiv.innerHTML = '<p class="no-results">No cards found. Try a different search!</p>';
        }
    } catch (error) {
        console.error('Search error:', error);
        resultsDiv.innerHTML = '<p class="error-message">❌ Error searching. Make sure the API is running!</p>';
    }
}

// Display search results
function displaySearchResults(results) {
    const resultsDiv = document.getElementById('searchResults');
    resultsDiv.innerHTML = '';
    
    results.forEach(card => {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'card-result';
        
        // Get available conditions
        const conditions = Object.keys(card.buylist_prices);
        const defaultCondition = conditions.includes('NM') ? 'NM' : conditions[0];
        
        cardDiv.innerHTML = `
            ${card.img_url ? `<img src="${card.img_url}" alt="${card.name}" onerror="this.style.display='none'">` : ''}
            <div class="card-name">${card.name}</div>
            <div class="card-set">${card.set_name} #${card.number}</div>
            
            <div class="price-display">
                <div class="price-row">
                    <span class="price-label">💵 Cash:</span>
                    <span class="price-value" id="cash-${card.card_id}">$${card.buylist_prices[defaultCondition].cash.toFixed(2)}</span>
                </div>
                <div class="price-row">
                    <span class="price-label">🎁 Credit:</span>
                    <span class="price-value" id="credit-${card.card_id}">$${card.buylist_prices[defaultCondition].credit.toFixed(2)}</span>
                </div>
            </div>
            
            <div class="condition-selector">
                <select id="condition-${card.card_id}" onchange="updateCardPrice(${card.card_id})">
                    ${conditions.map(cond => `
                        <option value="${cond}" ${cond === defaultCondition ? 'selected' : ''}>
                            ${cond} - ${getConditionLabel(cond)}
                        </option>
                    `).join('')}
                </select>
            </div>
            
            <button class="add-button" onclick="addToCart(${card.card_id})">
                ➕ Add to Buylist
            </button>
        `;
        
        resultsDiv.appendChild(cardDiv);
    });
}

// Update card price when condition changes
function updateCardPrice(cardId) {
    const card = searchResults.find(c => c.card_id === cardId);
    if (!card) return;
    
    const condition = document.getElementById(`condition-${cardId}`).value;
    const prices = card.buylist_prices[condition];
    
    document.getElementById(`cash-${cardId}`).textContent = `$${prices.cash.toFixed(2)}`;
    document.getElementById(`credit-${cardId}`).textContent = `$${prices.credit.toFixed(2)}`;
}

// Get condition label
function getConditionLabel(condition) {
    const labels = {
        'NM': 'Near Mint',
        'LP': 'Lightly Played',
        'MP': 'Moderately Played',
        'HP': 'Heavily Played',
        'DMG': 'Damaged'
    };
    return labels[condition] || condition;
}

// Add card to cart
function addToCart(cardId) {
    const card = searchResults.find(c => c.card_id === cardId);
    if (!card) return;
    
    const condition = document.getElementById(`condition-${cardId}`).value;
    const prices = card.buylist_prices[condition];
    
    // Check if card already in cart
    const existingIndex = cart.findIndex(item => 
        item.card_id === cardId && item.condition === condition
    );
    
    if (existingIndex !== -1) {
        // Increase quantity
        cart[existingIndex].quantity += 1;
    } else {
        // Add new item
        cart.push({
            card_id: cardId,
            name: card.name,
            set_name: card.set_name,
            number: card.number,
            condition: condition,
            quantity: 1,
            cash_price: prices.cash,
            credit_price: prices.credit
        });
    }
    
    updateCartDisplay();
    
    // Visual feedback
    const button = event.target;
    const originalText = button.textContent;
    button.textContent = '✅ Added!';
    button.style.background = '#4CAF50';
    setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '';
    }, 1000);
}

// Update cart display
function updateCartDisplay() {
    const cartCount = document.getElementById('cartCount');
    const cartItems = document.getElementById('cartItems');
    const cartSummary = document.getElementById('cartSummary');
    const emptyCart = document.getElementById('emptyCart');
    
    const totalItems = cart.reduce((sum, item) => sum + item.quantity, 0);
    cartCount.textContent = totalItems;
    
    if (cart.length === 0) {
        cartItems.innerHTML = '';
        cartSummary.style.display = 'none';
        emptyCart.style.display = 'block';
        return;
    }
    
    emptyCart.style.display = 'none';
    cartSummary.style.display = 'block';
    
    // Display cart items
    cartItems.innerHTML = cart.map((item, index) => `
        <div class="cart-item">
            <div class="cart-item-info">
                <h4>${item.name}</h4>
                <div class="cart-item-details">
                    ${item.set_name} • ${item.condition} • Qty: ${item.quantity}
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 15px;">
                <div class="cart-item-price" id="item-price-${index}">
                    $${(getCurrentPayoutMethod() === 'cash' ? item.cash_price : item.credit_price).toFixed(2)}
                </div>
                <button class="remove-button" onclick="removeFromCart(${index})">🗑️</button>
            </div>
        </div>
    `).join('');
    
    updateTotal();
}

// Remove from cart
function removeFromCart(index) {
    cart.splice(index, 1);
    updateCartDisplay();
}

// Get current payout method
function getCurrentPayoutMethod() {
    return document.querySelector('input[name="payout"]:checked').value;
}

// Update total
function updateTotal() {
    const payoutMethod = getCurrentPayoutMethod();
    
    const total = cart.reduce((sum, item) => {
        const price = payoutMethod === 'cash' ? item.cash_price : item.credit_price;
        return sum + (price * item.quantity);
    }, 0);
    
    document.getElementById('totalAmount').textContent = `$${total.toFixed(2)}`;
    
    // Update individual item prices in cart
    cart.forEach((item, index) => {
        const priceElement = document.getElementById(`item-price-${index}`);
        if (priceElement) {
            const price = payoutMethod === 'cash' ? item.cash_price : item.credit_price;
            priceElement.textContent = `$${(price * item.quantity).toFixed(2)}`;
        }
    });
}

// Submit buylist
async function submitBuylist() {
    const email = document.getElementById('customerEmail').value.trim();
    const name = document.getElementById('customerName').value.trim();
    const payoutMethod = getCurrentPayoutMethod();
    
    // Validation
    if (!email || !email.includes('@')) {
        alert('Please enter a valid email address');
        return;
    }
    
    if (cart.length === 0) {
        alert('Your cart is empty!');
        return;
    }
    
    // Prepare data
    const buylistData = {
        customer: {
            email: email,
            name: name || undefined
        },
        payout_method: payoutMethod,
        cards: cart.map(item => ({
            card_id: item.card_id,
            condition: item.condition,
            quantity: item.quantity
        }))
    };
    
    // Show loading
    document.getElementById('loadingSpinner').style.display = 'flex';
    
    try {
        const response = await fetch(`${API_URL}/buylist/submit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(buylistData)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess(data);
        } else {
            throw new Error(data.error || 'Submission failed');
        }
    } catch (error) {
        console.error('Submit error:', error);
        alert('❌ Error submitting buylist. Make sure the API is running!\n\n' + error.message);
    } finally {
        document.getElementById('loadingSpinner').style.display = 'none';
    }
}

// Show success message
function showSuccess(data) {
    const message = `
        <strong>Quote #${data.buy_offer_id}</strong><br><br>
        Total: $${data.quoted_total.toFixed(2)} (${data.payout_method})<br>
        Items: ${data.item_count} card${data.item_count > 1 ? 's' : ''}<br><br>
        We'll review your submission and email you at:<br>
        <strong>${document.getElementById('customerEmail').value}</strong><br><br>
        Quote expires: ${new Date(data.expires_at).toLocaleDateString()}
    `;
    
    document.getElementById('successText').innerHTML = message;
    document.getElementById('successMessage').style.display = 'flex';
    
    // Clear cart
    cart = [];
    updateCartDisplay();
}

// Helper: Format currency
function formatCurrency(amount) {
    return `$${amount.toFixed(2)}`;
}

// Console welcome message
console.log('%c🎴 Dumpling Collectibles Buylist', 'font-size: 20px; font-weight: bold; color: #667eea;');
console.log('%cMade with ❤️', 'font-size: 14px; color: #666;');
console.log('API URL:', API_URL);
