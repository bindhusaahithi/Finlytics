CREATE DATABASE finlytics;
USE finlytics;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);

CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    category_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    type VARCHAR(20) NOT NULL,
    description VARCHAR(255),
    transaction_date DATE NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE budgets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    category_id INT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    budget_month DATE NOT NULL,
    monthly_limit DECIMAL(10,2) NOT NULL,
    UNIQUE KEY unique_budget_per_month (
        user_id,
        category_id,
        currency,
        budget_month
    ),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE debts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    debt_name VARCHAR(150) NOT NULL,
    lender_name VARCHAR(150),
    country VARCHAR(100),
    currency VARCHAR(10) NOT NULL,
    original_amount DECIMAL(12,2) NOT NULL,
    interest_rate DECIMAL(6,3),
    due_date DATE,
    notes VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE debt_payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    debt_id INT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    payment_date DATE NOT NULL,
    notes VARCHAR(255),
    transaction_id INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (debt_id) REFERENCES debts(id) ON DELETE CASCADE,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
);

INSERT INTO categories (name)
SELECT 'Debt Payment'
WHERE NOT EXISTS (
    SELECT 1
    FROM categories
    WHERE name = 'Debt Payment'
);

SHOW DATABASES;

SHOW TABLES;

DESCRIBE users;
