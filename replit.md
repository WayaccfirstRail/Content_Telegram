# Overview

This is a professional Telegram bot designed for content creators who monetize their content through Telegram Stars. The bot serves as a complete fan engagement and content management platform, allowing creators to sell media content, interact with fans through AI-style responses, and manage their community directly through Telegram chat without needing external tools or interfaces.

The bot provides a dual interface: fans can browse teasers, purchase content with Telegram Stars, and have natural conversations, while content creators get comprehensive admin controls for content management, user analytics, and automated interactions.

# Recent Changes

**September 17, 2025 - Replit Environment Setup**
- Successfully configured the Telegram bot to run in Replit environment
- Set up required secrets: BOT_TOKEN and OWNER_ID
- Configured Flask web server on port 5000 with webview output
- Database initialization working properly with SQLite
- Bot polling and Flask server running concurrently via threading
- Deployment configured for VM target to maintain persistent operation

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Framework and Hosting
- **pyTelegramBotAPI (telebot)**: Core bot framework for handling Telegram API interactions
- **Flask**: Minimal web server to maintain bot presence on Replit hosting platform
- **Threading**: Separates Flask server and bot polling to ensure continuous operation
- **Environment Variables**: Secure storage of BOT_TOKEN and OWNER_ID through Replit Secrets

## Data Layer
- **SQLite Database**: Local file-based storage solution chosen for simplicity and zero-configuration deployment
- **Database Schema Design**:
  - Users table: Tracks fan demographics, spending history, and engagement metrics
  - Content items table: Stores purchasable content with pricing and file references
  - Responses table: Key-value store for AI-style conversational responses
  - Scheduled posts table: Time-based content delivery system
  - Loyal fans table: Creator-defined fan recognition system

## Payment Processing
- **Telegram Stars Integration**: Native Telegram cryptocurrency for seamless in-chat transactions
- **Invoice Generation**: Automated billing system with `bot.send_invoice` using XTR currency
- **Payment Workflow**: Handles pre-checkout validation and successful payment processing
- **Automatic Content Delivery**: Post-payment content distribution with user statistics updates

## User Interface Design
- **Command-Based Interaction**: Structured commands for specific actions (/start, /buy, /teaser)
- **Inline Keyboard Buttons**: Visual interface elements for common actions
- **Natural Language Fallback**: AI-style responses for conversational messages outside command structure
- **Dual Permission System**: Separate command sets for regular users and content creator (owner)

## Content Management System
- **In-Chat Administration**: Complete bot management through Telegram messages, eliminating need for external interfaces
- **Dynamic Content Addition**: Real-time content catalog updates without code modifications
- **File Handling**: Support for various media types through file paths or URLs
- **Scheduled Publishing**: Time-based content release system with datetime parsing

## Analytics and User Management
- **User Activity Tracking**: Comprehensive interaction logging and spending analysis
- **Loyalty System**: Creator-defined fan recognition with custom tagging
- **User Lifecycle Management**: User deletion and recovery with backup functionality
- **Engagement Analytics**: Stars earned tracking, top fan identification, and interaction metrics

# External Dependencies

## Telegram API
- **Telegram Bot API**: Core messaging and bot functionality through official API
- **Telegram Stars**: Native payment processing system for content monetization
- **Webhook/Polling**: Bot communication method with Telegram servers

## Python Libraries
- **pyTelegramBotAPI (telebot)**: Primary bot framework for Telegram integration
- **Flask**: Web server framework for Replit hosting compatibility
- **sqlite3**: Built-in Python library for database operations
- **threading**: Standard library for concurrent operation management
- **datetime**: Time handling for scheduling and analytics
- **logging**: Error tracking and debugging information
- **os**: Environment variable access for secure configuration

## Hosting Platform
- **Replit**: Cloud hosting platform with integrated environment variable management
- **Replit Secrets**: Secure storage system for sensitive configuration data (BOT_TOKEN, OWNER_ID)

## File Storage
- **Local File System**: Media content storage on hosting platform
- **URL References**: Support for external content hosting through direct links