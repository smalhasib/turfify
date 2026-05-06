# Project Requirements Document (PRD)
## Turf Management & Booking Platform

---

### 1. Document Overview
This document outlines the functional, non-functional, and technical requirements for building an independent, custom Turf Management and Booking System. The platform is designed to handle time-slot-based bookings, secure online payment processing, and administrative controls tailored to the Bangladeshi market.

---

### 2. Project Context & Objectives
* **Business Model:** Hourly rentals of sports turf (default pricing around BDT 1,000/hour, subject to adjustment).
* **Target Audience:** Sports enthusiasts booking slots on the go (highly mobile-centric).
* **Expected Daily Traffic:** 500 to 1,000 daily visits.
* **Key Integration Focus:** Bangladeshi local payment methods (MFS: bKash, Nagad, etc.) and secure phone-based verification.

---

### 3. Core Functional Requirements

#### 3.1. User Authentication (Mobile-First)
* **Phone Number Login:** Users must register and log in using their active mobile phone number.
* **OTP Verification:** Integration with a reliable SMS Gateway to send and verify One-Time Passwords (OTPs) during login/registration.
* **Profile Management:** Basic profile containing Name, Phone Number, and booking history.

#### 3.2. Booking Engine (Time-Slot Selection)
* **Daily Scheduling:** A 24-hour format interactive calendar showcasing available slots day-by-day.
* **Hourly Slots:** Ability to select specific hourly slots (e.g., 4:00 PM – 5:00 PM).
* **Race-Condition Prevention:** Mechanism to lock a slot temporarily (e.g., for 5 minutes) when a user initiates checkout, preventing double-bookings.
* **Interactive UI:** Visually clear differentiation between Available, Reserved, Selected, and Closed slots (similar to movie theater seat bookings).

#### 3.3. Payment Gateway Integration
* **Primary Gateway:** Integration with **SSLCommerz** (or similar compliant local aggregators).
* **Payment Methods:** Direct support for Mobile Financial Services (MFS) including **bKash**, **Nagad**, and **Rocket**, along with major credit/debit cards.
* **Instant Confirmation:** Webhook integration to capture payment confirmation status instantly and update the database.

#### 3.4. Post-Booking & Notification System
* **Dynamic Receipt Generation:** Automatic creation of a downloadable PDF receipt/invoice upon successful payment.
* **SMS Notifications:** Automated confirmation SMS sent to the user's phone number containing the Booking ID, Date, Time, and Payment Status.

---

### 4. Admin Management Dashboard

#### 4.1. Booking & Schedule Controls
* **Master Schedule Override:** Admin must have the capability to manually block slots for maintenance, tournaments, or offline corporate bookings.
* **Pricing Engine:** Easily adjust the base hourly rate (e.g., setting premium pricing for weekend evening slots or discounts for morning slots).

#### 4.2. Reporting & Analytics
* **Daily/Weekly/Monthly Revenue Reports:** Detailed breakdowns of earnings from online transactions.
* **Occupancy Rate Analytics:** Visual representations showing peak times, popular days, and slot utilization metrics.
* **Customer Log:** A database of registered customers with their booking counts and total spend.

---

### 5. Non-Functional & Technical Requirements

#### 5.1. Scalability & Performance
* **Traffic Handling:** Optimized to smoothly handle up to 1,000 daily active users, with concurrency management during peak booking periods (e.g., evening rush).
* **Page Load Time:** Under 2 seconds on mobile connections (4G/3G).

#### 5.2. Technical Stack Recommendation
* **Frontend:** React.js, Svelte, or Vue.js (Single Page Application architecture is highly recommended for reactive, fast-paced slot booking interfaces).
* **Backend:** Node.js (Express), FastAPI, or Laravel.
* **Database:** PostgreSQL (for robust relational data management) coupled with Redis (for handling active slot-booking locks and session caching).
* **Hosting:** Virtual Private Server (VPS) hosted in a geographically close region (e.g., Singapore or India) to maintain low latency for Bangladeshi users.

#### 5.3. Security & Compliance
* **HTTPS/SSL:** Mandated for all pages, especially checkout and user authentication.
* **Data Validation:** Strict backend sanitization of inputs to prevent SQL injections or XSS attacks.

---

### 6. Estimated Infrastructure & Costing Breakdown (Bangladesh Market)

The following table details the estimated annual operating expenses for running this platform:

| Cost Item | Service Type | Estimated Annual Cost (BDT) | Notes |
| :--- | :--- | :--- | :--- |
| **Domain Name** | Domain Registrar (.com or .com.bd) | BDT 1,500 – BDT 2,500 | Standard .com registration or BTCL (.com.bd) |
| **Cloud/VPS Hosting** | DigitalOcean, Linode, or AWS | BDT 12,000 – BDT 20,000 | Configured for 1k+ daily traffic & database requirements |
| **SMS Gateway API** | Greenweb, BulkSMSBD, etc. | BDT 5,000 – BDT 8,000 | Usage-based pricing (OTP + Confirmation SMS) |
| **SSLCommerz Integration** | Merchant Gateway Setup | *Free / Merchant Commission* | Merchant takes a ~2% to 3.5% cut on standard transactions |
| **Maintenance & Support** | System Admin / Minor bug fixes | BDT 10,000 – BDT 30,000 | Keeping libraries updated, server monitoring |
| **Total Estimated Yearly Cost** | | **BDT 28,500 – BDT 60,500** | *Excludes initial development/design agency cost* |
