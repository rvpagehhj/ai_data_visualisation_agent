import os
import json
import re
import sys
import io
import contextlib
import warnings
from typing import Optional, List, Any, Tuple
from PIL import Image
import streamlit as st
import pandas as pd
import base64
from io import BytesIO
from openai import OpenAI
from e2b_code_interpreter import Sandbox

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

pattern = re.compile(r"```python\n(.*?)\n```", re.DOTALL)

def code_interpret(e2b_code_interpreter: Sandbox, code: str) -> Optional[List[Any]]:
    with st.spinner('Executing code in E2B sandbox...'):
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                exec = e2b_code_interpreter.run_code(code)

        if stderr_capture.getvalue():
            print("[Code Interpreter Warnings/Errors]", file=sys.stderr)
            print(stderr_capture.getvalue(), file=sys.stderr)

        if stdout_capture.getvalue():
            print("[Code Interpreter Output]", file=sys.stdout)
            print(stdout_capture.getvalue(), file=sys.stdout)

        if exec.error:
            print(f"[Code Interpreter ERROR] {exec.error}", file=sys.stderr)
            return None
        return exec.results

def match_code_blocks(llm_response: str) -> str:
    match = pattern.search(llm_response)
    if match:
        code = match.group(1)
        return code
    return ""

def chat_with_llm(e2b_code_interpreter: Sandbox, user_message: str, dataset_path: str) -> Tuple[Optional[List[Any]], str]:
    # 更新系统提示词，包含数据集路径信息
    system_prompt = f"""你是一个Python数据科学家和数据可视化专家。你被提供了位于路径'{dataset_path}'的数据集以及用户的查询。
    你需要分析数据集并回答用户的查询，并通过运行Python代码来解决问题。
    重要：在代码中读取Excel文件时，必须始终使用数据集路径变量'{dataset_path}'。
    对于数据可视化，请使用常见的库，如matplotlib或plotly，这些库通常是可用的。
    不要使用pyecharts，seaborn或其他不太常见的可视化库。
    关键要求：
    1. 你必须在回复中生成一个且仅一个Python代码块
    2. 不要生成多个代码块——将所有必要的操作合并到一个代码块中
    3. 确保你的代码是完整且可以独立运行的"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    with st.spinner('Getting response from DeepSeek AI LLM model...'):
        client = OpenAI(
            api_key=st.session_state.deepseek_api_key,
            base_url="https://api.deepseek.com/v1"
        )
        response = client.chat.completions.create(
            model=st.session_state.model_name,
            messages=messages,
        )

        response_message = response.choices[0].message
        python_code = match_code_blocks(response_message.content)
        
        if python_code:
            code_interpreter_results = code_interpret(e2b_code_interpreter, python_code)
            return code_interpreter_results, response_message.content
        else:
            st.warning(f"Failed to match any Python code in model's response")
            return None, response_message.content

def upload_dataset(code_interpreter: Sandbox, uploaded_file) -> str:
    safe_filename = "dataset.xlsx"  # 使用简单的英文文件名
    dataset_path = f"./{safe_filename}"
    
    try:
        code_interpreter.files.write(dataset_path, uploaded_file)
        return dataset_path
    except Exception as error:
        st.error(f"Error during file upload: {error}")
        raise error


def main():
    """Main Streamlit application."""
    st.title("📊 AI Data Visualization Agent")
    st.write("Upload your dataset and ask questions about it!")

    # Initialize session state variables
    if 'deepseek_api_key' not in st.session_state:
        st.session_state.deepseek_api_key = ''
    if 'e2b_api_key' not in st.session_state:
        st.session_state.e2b_api_key = ''
    if 'model_name' not in st.session_state:
        st.session_state.model_name = ''

    with st.sidebar:
        st.header("API Keys and Model Configuration")
        st.session_state.deepseek_api_key = st.sidebar.text_input("DeepSeek AI API Key",
                                                                  value="sk-941ee361928e442dbef829307c5196d3",
                                                                  type="password")
        st.sidebar.info("💡 Get your DeepSeek API Key from DeepSeek platform")
        st.sidebar.markdown("[Get DeepSeek API Key](https://platform.deepseek.com/)")

        st.session_state.e2b_api_key = st.sidebar.text_input("Enter E2B API Key",
                                                             value="e2b_e5992a6c510c676f8b67688730f7f7d8b6fb9f16",
                                                             type="password")
        st.sidebar.markdown("[Get E2B API Key](https://e2b.dev/docs/legacy/getting-started/api-key)")
        
        # Add model selection dropdown
        model_options = {
            "DeepSeek Chat": "deepseek-chat",
            "DeepSeek Coder": "deepseek-coder"
        }
        st.session_state.model_name = st.selectbox(
            "Select Model",
            options=list(model_options.keys()),
            index=1  # Default to first option
        )
        st.session_state.model_name = model_options[st.session_state.model_name]

    #uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    uploaded_file = st.file_uploader("Choose an Excel file", type=["xlsx", "xls"])
    if uploaded_file is not None:
        # Display dataset with toggle
        df = pd.read_excel(uploaded_file)
        st.write("Dataset:")
        show_full = st.checkbox("Show full dataset")
        if show_full:
            st.dataframe(df)
        else:
            st.write("Preview (first 5 rows):")
            st.dataframe(df.head())
        # Query input
        query = st.text_area("What would you like to know about your data?",
                            "对数据进行可视化分析")
        
        if st.button("Analyze"):
            if not st.session_state.deepseek_api_key or not st.session_state.e2b_api_key:
                st.error("Please enter both API keys in the sidebar.")
            else:
                with Sandbox(api_key=st.session_state.e2b_api_key) as code_interpreter:
                    # Upload the dataset
                    dataset_path = upload_dataset(code_interpreter, uploaded_file)
                    
                    # Pass dataset_path to chat_with_llm
                    code_results, llm_response = chat_with_llm(code_interpreter, query, dataset_path)
                    
                    # Display LLM's text response
                    st.write("AI Response:")
                    st.write(llm_response)
                    
                    # Display results/visualizations
                    if code_results:
                        for result in code_results:
                            if hasattr(result, 'png') and result.png:  # Check if PNG data is available
                                # Decode the base64-encoded PNG data
                                png_data = base64.b64decode(result.png)
                                
                                # Convert PNG data to an image and display it
                                image = Image.open(BytesIO(png_data))
                                st.image(image, caption="Generated Visualization", use_container_width=False)
                            elif hasattr(result, 'figure'):  # For matplotlib figures
                                fig = result.figure  # Extract the matplotlib figure
                                st.pyplot(fig)  # Display using st.pyplot
                            elif hasattr(result, 'show'):  # For plotly figures
                                st.plotly_chart(result)
                            elif isinstance(result, (pd.DataFrame, pd.Series)):
                                st.dataframe(result)
                            else:
                                st.write(result)  

if __name__ == "__main__":
    main()

#E2B:e2b_e5992a6c510c676f8b67688730f7f7d8b6fb9f16
#DeepSeek:sk-941ee361928e442dbef829307c5196d3