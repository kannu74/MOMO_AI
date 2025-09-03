# Momo AI - Conversation Database System

## Overview

The Momo AI assistant now includes a conversation database system that stores all interactions locally, enabling context-aware conversations across sessions. This solves the limitation of Gemini's free API which doesn't provide conversation memory.

## Features

### 🔄 **Context Persistence**
- All conversations are stored in a local SQLite database
- Context from previous conversations is automatically included in new requests
- Sessions persist across application restarts

### 📊 **Conversation Management**
- View conversation history
- Export conversations to text files
- Delete old sessions
- Track session statistics

### 🎯 **Smart Context Enhancement**
- Automatically enhances prompts with relevant conversation history
- Maintains conversation flow and continuity
- Provides better, more contextual responses

## Database Structure

### Tables

#### `sessions`
- `id`: Primary key
- `session_id`: Unique session identifier
- `created_at`: Session creation timestamp
- `last_activity`: Last activity timestamp
- `total_messages`: Total messages in session

#### `conversations`
- `id`: Primary key
- `session_id`: Foreign key to sessions
- `timestamp`: Conversation timestamp
- `user_message`: User's input
- `ai_response`: AI's response
- `context_summary`: Optional context summary
- `metadata`: JSON metadata (enhanced prompt, error info, etc.)

## Usage

### Running the Assistant

The database system is automatically integrated into the main application:

```bash
python main.py
```

When you start the assistant:
1. A new session is automatically created
2. All conversations are stored in the database
3. Context from previous conversations is included in responses

### Managing Conversations

Use the conversation manager utility:

```bash
# List all sessions
python conversation_manager.py list

# View a specific session
python conversation_manager.py view --session-id session_20241201_143022_abc12345

# Export a session to file
python conversation_manager.py export --session-id session_20241201_143022_abc12345 --output my_conversation.txt

# Delete a session
python conversation_manager.py delete --session-id session_20241201_143022_abc12345
```

### Testing the Database

Test the database functionality:

```bash
python test_database.py
```

## How It Works

### 1. Session Initialization
When the assistant starts, a new session is created with a unique ID:
```
session_20241201_143022_abc12345
```

### 2. Conversation Storage
Every user message and AI response is stored in the database:
- User message is stored before processing
- AI response is stored after generation
- Metadata includes enhanced prompts and timestamps

### 3. Context Enhancement
Before sending to Gemini API:
- Recent conversation history is retrieved
- Context is added to the user's prompt
- Enhanced prompt is sent to Gemini
- Response maintains conversation continuity

### 4. Example Context Enhancement

**Original User Message:**
```
"What did we talk about earlier?"
```

**Enhanced Prompt Sent to Gemini:**
```
Previous conversation:
User: Hello, how are you?
You: I'm doing great! How can I help you today?
---
Previous conversation:
User: Can you help me with Python?
You: Absolutely! I'd love to help you with Python programming. What specific question do you have?
---

Current user message: What did we talk about earlier?

Please respond to the current message while considering the conversation context above.
```

## Configuration

### Database Location
The database file (`conversations.db`) is created in the project root directory.

### Context Limits
- Default: Last 5 conversations included in context
- Configurable in `get_conversation_history()` calls
- Maximum context length handled by Gemini API limits

### Session Management
- Sessions are automatically created on startup
- Session IDs include timestamp and unique identifier
- Sessions can be manually managed via conversation manager

## Benefits

### ✅ **Persistent Memory**
- Conversations remember previous context
- No need to repeat information
- Better user experience

### ✅ **Local Storage**
- All data stored locally
- No external dependencies for storage
- Privacy maintained

### ✅ **Flexible Management**
- Export conversations for analysis
- Delete old sessions to save space
- View conversation statistics

### ✅ **Enhanced Responses**
- More contextual and relevant answers
- Better conversation flow
- Improved user satisfaction

## Troubleshooting

### Database Errors
If you encounter database errors:
1. Check file permissions in the project directory
2. Ensure SQLite is available (built into Python)
3. Try deleting `conversations.db` to reset

### Context Issues
If context isn't working:
1. Check if sessions are being created
2. Verify conversation history is being stored
3. Test with `test_database.py`

### Performance
For large conversation histories:
- Consider limiting context to recent conversations
- Export and delete old sessions
- Monitor database file size

## Future Enhancements

- [ ] Conversation search functionality
- [ ] Automatic context summarization
- [ ] Multi-user support
- [ ] Conversation analytics
- [ ] Backup and restore functionality
- [ ] Web interface for conversation management 