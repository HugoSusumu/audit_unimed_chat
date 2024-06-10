import streamlit as st # Import python packages
from snowflake.snowpark.context import get_active_session
import pandas as pd

conn = st.connection("snowflake")
session = conn.session()



pd.set_option("max_colwidth",None)

### Default Values
st.session_state.model_name = 'reka-flash'
st.session_state.use_chat_history = True
st.session_state.debug = 1
#model_name = 'snowflake-arctic' #Default but we allow user to select one
num_chunks = 80 # Num-chunks provided as context. Play with this to check how it affects your accuracy
slide_window = 5 # how many last conversations to remember. This is the slide window.
debug = 1 #Set this to 1 if you want to see what is the text created as summary and sent to get chunks
use_chat_history = 0 #Use the chat history by default

### Functions

def main():
    
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image('https://www.unimed.coop.br/site/image/layout_set_logo?img_id=32576633&t=1714051077186')
    
    st.title(f"Audit Assistant")
    st.write("O documento que será utilizada para responder suas perguntas: ")
    st.write('VERSÃO 21. MANUAL DE CONSULTAS DAS NORMAS DE AUDITORIA MÉDICA E DE ENFERMAGEM V.21')

    config_options()
    init_messages()
     
    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Accept user input
    if question := st.chat_input(""):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(question)
        # Display assistant response in chat message container
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
    
            question = question.replace("'","")
    
            with st.spinner(f"Pensando..."):
                response = complete(question)
                res_text = response[0].RESPONSE     
            
                res_text = res_text.replace("'", "")
                message_placeholder.markdown(res_text)
        
        st.session_state.messages.append({"role": "assistant", "content": res_text})

def config_options():
    st.sidebar.button("Recomeçar", key="clear_conversation")


def init_messages():

    # Initialize chat history
    if st.session_state.clear_conversation or "messages" not in st.session_state:
        st.session_state.messages = []

    
def get_similar_chunks (question):

    cmd = """
        with results as
        (SELECT RELATIVE_PATH,
           VECTOR_COSINE_DISTANCE(docs_chunks_table.chunk_vec,
                    snowflake.cortex.embed_text('e5-base-v2', ?)) as distance,
           chunk
        from docs_chunks_table
        where relative_path = 'VERSÃO 21. MANUAL DE CONSULTAS DAS NORMAS DE AUDITORIA MÉDICA E DE ENFERMAGEM V.21.pdf'
        order by distance desc
        limit ?)
        select chunk, relative_path from results 
    """
    
    df_chunks = session.sql(cmd, params=[question, num_chunks]).to_pandas()       

    df_chunks_lenght = len(df_chunks) -1

    similar_chunks = ""
    for i in range (0, df_chunks_lenght):
        similar_chunks += df_chunks._get_value(i, 'CHUNK')

    similar_chunks = similar_chunks.replace("'", "")
             
    return similar_chunks


def get_chat_history():
#Get the history from the st.session_stage.messages according to the slide window parameter
    
    chat_history = []
    
    start_index = max(0, len(st.session_state.messages) - slide_window)
    for i in range (start_index , len(st.session_state.messages) -1):
         chat_history.append(st.session_state.messages[i])

    return chat_history

    
def summarize_question_with_history(chat_history, question):
# To get the right context, use the LLM to first summarize the previous conversation
# This will be used to get embeddings and find similar chunks in the docs for context

    prompt = f"""
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natual language. 
        Answer with only the query. Do not add any explanation.
        
        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        """
    
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    sumary = df_response[0].RESPONSE     

    # if st.session_state.debug:
    #     st.sidebar.text("Summary to be used to find similar chunks in the docs:")
    #     st.sidebar.caption(sumary)

    sumary = sumary.replace("'", "")

    return sumary

def create_prompt (myquestion):

    if st.session_state.use_chat_history:
        chat_history = get_chat_history()

        if chat_history != "": #There is chat_history, so not first question
            question_summary = summarize_question_with_history(chat_history, myquestion)
            prompt_context =  get_similar_chunks(question_summary)
        else:
            prompt_context = get_similar_chunks(myquestion) #First question when using history
    else:
        prompt_context = get_similar_chunks(myquestion)
        chat_history = ""
  
    prompt = f"""
           You are an expert chat assistance that extracs information from the CONTEXT provided
           between <context> and </context> tags.
           You offer a chat experience considering the information included in the CHAT HISTORY
           provided between <chat_history> and </chat_history> tags..
           When ansering the question contained between <question> and </question> tags
           be concise and do not hallucinate. 
           If you don´t have the information just say so.
                     
           Do not mention the CONTEXT used in your answer.
           Do not mention the CHAT HISTORY used in your asnwer.
           
           <chat_history>
           {chat_history}
           </chat_history>
           <context>          
           {prompt_context}
           </context>
           <question>  
           {myquestion}
           </question>
           Answer: 
           """

    return prompt


def complete(myquestion):

    prompt =create_prompt (myquestion)
    cmd = """
            select snowflake.cortex.complete(?, ?) as response
          """
    
    df_response = session.sql(cmd, params=[st.session_state.model_name, prompt]).collect()
    return df_response

if __name__ == "__main__":
    main()