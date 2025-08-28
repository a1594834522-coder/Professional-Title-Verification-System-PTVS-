
import os
import pandas as pd
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pypdf import PdfReader
import time

def _safe_basename(file_path: str) -> str:
    """安全地获取文件名，确保中文文件名正确显示"""
    try:
        # 获取基本文件名
        basename = os.path.basename(file_path)
        # 确保文件名是字符串格式
        if isinstance(basename, bytes):
            # 尝试用不同编码解码
            for encoding in ['utf-8', 'gbk', 'cp936']:
                try:
                    return basename.decode(encoding)
                except UnicodeDecodeError:
                    continue
            # 如果都失败了，使用错误处理
            return basename.decode('utf-8', errors='replace')
        return basename
    except Exception:
        return "未知文件"

def load_api_key():
    """从.env文件加载Google API密钥"""
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("无法找到Google API密钥，请检查.env文件")
    return api_key

def get_pdf_text(pdf_path):
    """提取单个PDF文件的所有文本（直接使用AI识别）"""
    filename = _safe_basename(pdf_path)
    
    print(f"🤖 直接使用AI识别: {filename}")
    return get_pdf_text_with_ai(pdf_path)

def get_pdf_text_with_ai(pdf_path):
    """使用AI直接识别PDF文件内容（采用Google推荐的最新方法，完整读取）"""
    import pathlib
    
    filename = _safe_basename(pdf_path)
    
    # 添加重试机制
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🤖 开始使用AI完整识别PDF ({attempt+1}/{max_retries}): {filename}")
            
            # 检查文件是否存在且有效
            if not os.path.exists(pdf_path):
                return f"无法读取PDF文件 {filename}: 文件不存在"
            
            file_size = os.path.getsize(pdf_path)
            if file_size == 0:
                return f"无法读取PDF文件 {filename}: 文件为空"
            elif file_size > 100 * 1024 * 1024:  # 100MB限制
                return f"无法读取PDF文件 {filename}: 文件过大（{file_size/1024/1024:.1f}MB），超出100MB限制"
            
            # 使用pathlib读取PDF文件（官方推荐方式）
            filepath = pathlib.Path(pdf_path)
            
            # 检查PDF文件头
            pdf_bytes = filepath.read_bytes()
            if not pdf_bytes.startswith(b'%PDF-'):
                return f"无法读取PDF文件 {filename}: 文件不是有效的PDF格式"
            
            # 初始化Google AI客户端
            api_key = load_api_key()
            client = genai.Client(api_key=api_key)
            
            # 使用Google AI官方推荐的最新方式直接识别PDF
            prompt = f"请非常仔细、完整地阅读并分析这个PDF文件（{filename}）的内容。请提取所有文本内容，包括标题、正文、表格、数据等。如果有图片或图表，请描述其内容。请以结构化的格式输出，保持原有的层次结构。不要遗漏任何内容。"
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=filepath.read_bytes(),
                        mime_type='application/pdf',
                    ),
                    prompt
                ]
            )
            
            if response and response.text:
                extracted_text = response.text.strip()
                print(f"✅ AI完整识别成功: {filename}，提取内容长度: {len(extracted_text)}字符")
                return extracted_text
            else:
                print(f"⚠️ AI识别失败，未收到有效响应: {filename}")
                if attempt < max_retries - 1:
                    print(f"⏳ 等待后重试 ({attempt+2}/{max_retries})...")
                    time.sleep(3 ** attempt)  # 指数退避
                    continue
                else:
                    return f"无法读取PDF文件 {filename}: AI识别失败，未收到有效响应"
                    
        except Exception as e:
            error_msg = str(e)
            print(f"❌ AI识别PDF失败 ({attempt+1}/{max_retries}): {filename} - {error_msg}")
            
            if "too large" in error_msg.lower() or "size" in error_msg.lower():
                return f"无法读取PDF文件 {filename}: 文件过大，AI无法处理"
            else:
                # 如果不是最后一次尝试，等待一段时间再重试
                if attempt < max_retries - 1:
                    print(f"⏳ 等待后重试 ({attempt+2}/{max_retries})...")
                    time.sleep(3 ** attempt)  # 指数退避
                    continue
                else:
                    return f"无法读取PDF文件 {filename}: AI识别失败 - {str(e)}"
        
        # 如果循环正常结束，说明重试成功
        break
    
    # 这里不应该到达，但如果到达了，返回一个错误信息
    return f"无法读取PDF文件 {filename}: 未知错误"

def get_excel_data_as_markdown(excel_path):
    """读取Excel文件并转换为Markdown表格"""
    try:
        df = pd.read_excel(excel_path)
        return df.to_markdown(index=False)
    except Exception as e:
        return f"无法读取Excel文件 {_safe_basename(excel_path)}: {e}"

def main():
    """主执行函数"""
    try:
        # 设置
        materials_dir = 'materials'
        api_key = load_api_key()

        # 检查并创建materials目录
        if not os.path.exists(materials_dir):
            os.makedirs(materials_dir)
            print(f"已创建 '{materials_dir}' 目录")
            print("请将您的PDF文件和Excel清单文件放入此目录中，然后重新运行程序。")
            print(f"完整路径：{os.path.abspath(materials_dir)}")
            return

        # 寻找材料文件
        try:
            pdf_files = [f for f in os.listdir(materials_dir) if f.lower().endswith('.pdf')]
            excel_files = [f for f in os.listdir(materials_dir) if f.lower().endswith(('.xlsx', '.xls'))]
        except Exception as e:
            print(f"无法访问 '{materials_dir}' 目录: {e}")
            return

        if not pdf_files:
            print(f"在 '{materials_dir}' 目录中没有找到PDF文件。")
            print(f"请将您的PDF文件放入：{os.path.abspath(materials_dir)}")
            return
        
        print(f"找到 {len(pdf_files)} 个PDF文件：{', '.join(pdf_files)}")
        print("📄 将使用混合PDF处理策略：先pypdf快速提取，再AI智能识别")

        # 提取所有PDF内容（使用混合策略）
        all_pdf_texts = []
        for pdf_file in pdf_files:
            pdf_path = os.path.join(materials_dir, pdf_file)
            pdf_content = get_pdf_text(pdf_path)  # 现在使用混合策略
            all_pdf_texts.append(f"--- 文件名: {pdf_file} ---\n{pdf_content}")
        
        pdf_context = "\n\n".join(all_pdf_texts)

        # 提取Excel内容
        excel_context = "没有提供Excel清单。"
        if excel_files:
            excel_path = os.path.join(materials_dir, excel_files[0]) # 默认使用第一个找到的Excel
            excel_context = get_excel_data_as_markdown(excel_path)
            print(f"找到Excel清单文件：{excel_files[0]}")
        else:
            print(f"警告: 在 '{materials_dir}' 目录中没有找到Excel文件，将仅对PDF内容进行一致性检查。")


        # 初始化Google Gen AI客户端
        client = genai.Client(api_key=api_key)

        # 构建提示内容
        prompt_content = f"""
        你是一位经验丰富、严谨细致的职称评审委员会成员。你的任务是仔细审查以下所有申请材料，找出其中的矛盾、不一致、夸大或不合理之处。同时，请根据提供的佐证材料清单（来自Excel文件），核对是否有缺失的材料。你需要有AI判断能力，即使字段名或描述不完全对应，也能识别出是同一份材料。

        请遵循以下审查标准：
        1.  **交叉验证**：对比不同PDF文件中的相同信息点（如项目名称、起止时间、个人角色、成果数据等）是否完全一致。
        2.  **合理性分析**：评估所描述的工作内容、项目成果是否真实可信，有无夸大成分。
        3.  **完整性核对**：将所有PDF材料与Excel清单进行比对，列出清单上要求但未在PDF中体现的缺失项。

        你的最终报告需要清晰地分点列出所有发现的问题，并明确指出问题来源于哪个文件（文件名）。

        --- 佐证材料清单 (来自Excel文件) ---
        {excel_context}

        --- 已提交的佐证材料 (来自所有PDF文件) ---
        {pdf_context}

        请开始你的评审，并生成最终的审查报告：
        """

        # 执行并打印结果
        print("正在调用AI进行交叉检验，请稍候...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_content
        )
        
        print("\n--- AI审查报告 ---")
        print(response.text)

    except Exception as e:
        print(f"程序发生错误: {e}")

if __name__ == "__main__":
    main()
