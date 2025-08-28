# CLAUDE.md

核心要求：永远用中文回答！！！！
你不需要帮我写测试文件！！！我自己会测试！！！

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **职称评审材料交叉检验系统** (Professional Title Review Material Cross-Validation System) - a Flask web application that uses Google Gemini AI to analyze PDF documents for professional title review. The system performs cross-validation of submitted materials to detect inconsistencies, inaccuracies, and missing documents.

## Development Commands

### Setup and Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application locally
python app.py

# Test API rotation mechanism
python test_api_rotation.py

# Diagnose processing issues
python diagnose_stuck_issue.py
```

### Environment Configuration
Create a `.env` file with the following variables:
```env
# 方法1：批量配置（推荐）- 支持逗号、换行混合分隔
GOOGLE_API_KEYS=key1,key2,key3,key4,key5

# 方法2：传统的单独配置方式
# GOOGLE_API_KEY=your_primary_api_key_here
# GOOGLE_API_KEY_2=your_second_api_key_here
# GOOGLE_API_KEY_3=your_third_api_key_here
# GOOGLE_API_KEY_4=your_fourth_api_key_here
# GOOGLE_API_KEY_5=your_fifth_api_key_here

# Flask secret key
SECRET_KEY=your_random_secret_key_here
```

### Deployment
- **Local Development**: `python app.py` (runs on port 5000)
- **Cloudflare Pages**: Use `wrangler.toml` configuration
- **Firewall Setup**: Run `setup_firewall.bat` as administrator for Windows

## Architecture Overview

### Core Components

1. **Flask Web Application** (`app.py`):
   - Main web server handling file uploads and background task management
   - Uses threading for background processing
   - Supports both ZIP and individual PDF file uploads
   - Real-time progress tracking via WebSocket-like polling

2. **Cross Validation Engine** (`cross_validator.py`):
   - Core analysis engine using Google Gemini AI
   - Implements API rotation mechanism for multiple API keys
   - Handles PDF text extraction (pypdf + AI fallback)
   - Rule-based validation system with priority levels
   - Concurrent processing with thread pools

3. **PDF Processing** (`cross_check.py`):
   - Hybrid PDF processing: pypdf first, then AI recognition
   - Handles Chinese filename encoding issues
   - File size limitations and error handling

4. **Rule System** (`rules/` directory):
   - Excel-based rule definitions for different material types
   - Markdown-based general rules (`rules/通用规则.md`)
   - Priority-based rule application (极高/高/中/低)

### Key Features

- **Multi-API Key Rotation**: Automatic switching between multiple Google API keys to avoid rate limits
- **Hybrid PDF Processing**: Fast pypdf extraction with AI fallback for complex documents
- **Chinese Language Support**: Proper handling of Chinese filenames and content
- **Background Processing**: Non-blocking file processing with real-time progress updates
- **Rule-Based Validation**: Configurable validation rules with priority levels
- **Cross-Validation**: Checks for consistency across multiple documents
- **Responsive Web UI**: Mobile-friendly interface with drag-and-drop upload

### Material Types
The system recognizes 17 different types of professional review materials:
1. 教育经历 (Education History)
2. 工作经历 (Work Experience) 
3. 继续教育(培训情况) (Continuing Education)
4. 学术技术兼职情况 (Academic Positions)
5. 获奖情况 (Awards)
6. 获得荣誉称号情况 (Honorary Titles)
7. 主持参与科研项目(基金)情况 (Research Projects)
8. 主持参与工程技术项目情况 (Engineering Projects)
9. 论文 (Papers)
10. 著(译)作(教材) (Publications)
11. 专利(著作权)情况 (Patents)
12. 主持参与指定标准情况 (Standards)
13. 成果被批示、采纳、运用和推广情况 (Achievement Recognition)
14. 资质证书 (Certificates)
15. 奖惩情况 (Rewards/Penalties)
16. 考核情况 (Performance Reviews)
17. 申报材料附件信息 (Application Attachments)

## Important Implementation Details

### API Rotation System
- Automatically detects and uses multiple API keys from environment variables
- Implements intelligent key selection (least used first)
- Error handling with automatic blacklisting (3 consecutive errors)
- Rate limiting with exponential backoff and jitter

### File Processing Flow
1. ZIP extraction with encoding fix for Chinese filenames
2. File-to-material type mapping based on folder/filename patterns
3. Concurrent PDF processing (pypdf + AI fallback)
4. Rule application and validation
5. Cross-validation analysis
6. Report generation in Markdown format

### Error Handling
- Comprehensive error handling for PDF extraction failures
- Graceful degradation when AI services are unavailable
- Timeout handling for long-running processes
- Detailed logging and progress reporting

### Security Considerations
- File type validation (PDF, ZIP, Excel only)
- File size limits (10MB for AI processing)
- Temporary file cleanup
- Safe filename handling for uploads
- Secret key management via environment variables

## Development Notes

- Uses Python 3.11 (see `runtime.txt`)
- All Chinese text and filenames are properly encoded/decoded
- Concurrent processing limited to 3-4 threads to avoid resource exhaustion
- Progress callbacks provide real-time user feedback
- System includes diagnostic tools for troubleshooting