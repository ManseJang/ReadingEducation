import streamlit as st
import requests
import re
import json
from bs4 import BeautifulSoup
from openai import OpenAI

# === API 키 설정 ===
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=OPENAI_API_KEY)

# === 유틸리티 함수들 ===

def remove_html_tags(text):
    """HTML 태그 제거"""
    if not text:
        return ""
    clean = re.compile(r"<.*?>")
    return re.sub(clean, "", text)

def remove_code_fences(text: str) -> str:
    """
    ChatGPT 응답에 포함된 ```json, ``` 코드 블록을 제거하고,
    앞뒤 공백을 strip하여 순수 JSON만 남기는 함수.
    """
    text = text.strip()
    # 앞부분의 ```json 또는 ``` 제거
    text = re.sub(r"^```(json)?", "", text)
    # 뒷부분의 ``` 제거
    text = re.sub(r"```$", "", text)
    # 혹시 맨 앞에 'json'만 남아있는 경우 제거
    text = text.strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()
    return text

def get_chatgpt_response(prompt, system_prompt=None):
    """단일 프롬프트에 대한 ChatGPT 응답"""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # 필요에 따라 모델명 조정
            messages=messages,
            temperature=0.5,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error: {e}"

def get_chatgpt_chat_response(chat_history):
    """대화 이력 전체에 대한 ChatGPT 응답"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # 필요에 따라 모델명 조정
            messages=chat_history,
            temperature=0.5,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error: {e}"

def search_books(query):
    """네이버 도서 API를 사용하여 책 검색"""
    url = "https://openapi.naver.com/v1/search/book.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": 10,    
        "start": 1,
        "sort": "sim"     
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
    except Exception as e:
        st.error(f"네이버 API 응답 처리 중 에러 발생: {e}")
        return []
    books = data.get("items", [])
    return books

def get_synopsis_from_naverbook(book_title):
    """네이버 책 상세 페이지 크롤링을 통해 줄거리 정보 가져오기"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # 1) 네이버 책 검색 페이지에서 첫번째 결과 링크 추출
        search_url = f"https://book.naver.com/search/search.nhn?query={book_title}"
        search_response = requests.get(search_url, headers=headers)
        search_soup = BeautifulSoup(search_response.text, "html.parser")
        first_link = search_soup.select_one("ul.list_type1 li a")
        if first_link is None:
            return None

        detail_url = "https://book.naver.com" + first_link.get("href")
        # 2) 상세 페이지 요청 후 줄거리 정보 추출
        detail_response = requests.get(detail_url, headers=headers)
        detail_soup = BeautifulSoup(detail_response.text, "html.parser")
        summary_div = detail_soup.find("div", class_="book_intro")
        if summary_div:
            summary_text = summary_div.get_text(separator="\n").strip()
            return summary_text
        else:
            return None
    except Exception as e:
        st.error(f"네이버 도서 상세 페이지 크롤링 중 에러 발생: {e}")
        return None

def get_combined_synopsis(book_title, book_data):
    """네이버 API의 description + 크롤링 데이터를 합쳐서 최종 줄거리 반환"""
    naver_description = remove_html_tags(book_data.get("description", "줄거리 정보가 없습니다."))
    naverbook_synopsis = get_synopsis_from_naverbook(book_title)
    if naverbook_synopsis:
        combined = naver_description + "\n\n" + naverbook_synopsis
    else:
        combined = naver_description
    return combined

def rewrite_synopsis_for_elementary(book_title, combined_synopsis):
    """초등학생용 쉬운 문장으로 줄거리 재작성"""
    prompt = (
        f"다음 책 '{book_title}'의 줄거리 정보를 바탕으로, 네이버 API와 크롤링 데이터를 이용한 내용만을 사용하여, "
        "초등학생들이 쉽게 이해할 수 있도록 쉬운 어휘와 구체적인 내용을 사용해 20줄 이상의 줄거리로 자연스럽게 정리해줘. "
        "내용에 API나 크롤링 티가 나지 않도록, 진짜 책 줄거리처럼 재구성해줘.\n\n"
        f"원본 줄거리:\n{combined_synopsis}"
    )
    with st.spinner("줄거리 재작성 중..."):
        rewritten = get_chatgpt_response(prompt)
    return rewritten

# === 페이지별 함수 ===

def page_book_search():
    st.header("📚 책 검색")

    # 사이드바 초기화 버튼 (해당 페이지만 초기화)
    if st.sidebar.button("책 검색 페이지 초기화"):
        st.session_state.selected_book = None
        st.session_state.search_results = None
        st.session_state.selected_synopsis_final = None
        st.rerun()

    st.markdown("### 책 제목 또는 키워드로 검색")
    col1, col2 = st.columns([1, 2])

    with col1:
        with st.form("search_form", clear_on_submit=False):
            query = st.text_input("검색어 입력", value="")
            submitted = st.form_submit_button("검색")
            if submitted:
                if query.strip() == "":
                    st.error("검색어를 입력해주세요!")
                else:
                    with st.spinner("책 정보를 가져오는 중..."):
                        books = search_books(query)
                    if books:
                        st.success(f"{len(books)}개의 책 정보를 찾았습니다!")
                        st.session_state.search_results = books
                    else:
                        st.warning("검색 결과가 없습니다. API 키, 파라미터 또는 검색어를 확인해 주세요.")

    with col2:
        if "search_results" in st.session_state and st.session_state.search_results:
            st.markdown("#### 검색 결과")
            books = st.session_state.search_results
            book_options = []
            for book in books:
                title = remove_html_tags(book.get("title", "제목 없음"))
                author = remove_html_tags(book.get("author", "저자 정보 없음"))
                publisher = remove_html_tags(book.get("publisher", "출판사 정보 없음"))
                display_str = f"{title} | {author} | {publisher}"
                book_options.append((display_str, book))

            selected_option = st.selectbox(
                "검색 결과에서 책을 선택하세요.",
                options=book_options,
                format_func=lambda x: x[0]
            )

            if st.button("이 책 선택"):
                st.session_state.selected_book = selected_option[1]
                book_title = remove_html_tags(selected_option[1].get("title", "제목 없음"))
                st.success(f"'{book_title}' 책이 선택되었습니다.")
                # 결합된 줄거리 생성
                combined_synopsis = get_combined_synopsis(book_title, selected_option[1])
                # 초등학생용 줄거리 재작성
                final_synopsis = rewrite_synopsis_for_elementary(book_title, combined_synopsis)
                st.session_state.selected_synopsis_final = final_synopsis
                st.markdown("**줄거리 (초등학생용 재작성):**")
                st.write(final_synopsis)

            if st.button("독서 퀴즈로 이동"):
                st.session_state.current_page = "독서 퀴즈"
                st.rerun()

    # 이미 책이 선택된 경우, 선택 정보 표시
    if st.session_state.get("selected_book"):
        selected_book = st.session_state.selected_book
        title = remove_html_tags(selected_book.get("title", "제목 없음"))
        author = remove_html_tags(selected_book.get("author", "저자 정보가 없음"))
        publisher = remove_html_tags(selected_book.get("publisher", "출판사 정보 없음"))
        st.info(f"현재 선택된 책: {title} | {author} | {publisher}")

        if st.button("선택된 책 변경"):
            st.session_state.selected_book = None
            st.session_state.search_results = None
            st.session_state.selected_synopsis_final = None
            st.rerun()


def page_reading_quiz():
    st.header("📝 독서 퀴즈 생성 및 풀이")

    if st.sidebar.button("독서 퀴즈 페이지 초기화"):
        for key in ["quiz_data", "quiz_answers"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    if "selected_book" not in st.session_state or st.session_state.selected_book is None:
        st.error("선택된 책이 없습니다. 먼저 '책 검색' 페이지에서 책을 선택하세요.")
        return

    selected_book = st.session_state.selected_book
    book_title = remove_html_tags(selected_book.get("title", "제목 없음"))
    book_synopsis = st.session_state.get("selected_synopsis_final") or remove_html_tags(
        selected_book.get("description", "줄거리 정보가 없습니다.")
    )

    st.markdown(f"**책 제목:** {book_title}")

    # 1) 퀴즈 생성
    if "quiz_data" not in st.session_state:
        if st.button("퀴즈 생성"):
            prompt = (
                f"다음 책 '{book_title}'의 줄거리를 바탕으로 3개의 4지 선다형 독서 퀴즈 문제를 JSON 형식으로 생성해줘. "
                "출력 형식 예시는 아래와 같이 해:\n\n"
                "{\n"
                '  "quiz": [\n'
                "    {\n"
                '      "question": "문제 내용",\n'
                '      "options": ["선택지1", "선택지2", "선택지3", "선택지4"],\n'
                '      "correct_answer": "선택지1"\n'
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}\n\n"
                "답안은 오직 JSON 형식으로만 출력해줘.\n\n"
                f"줄거리:\n{book_synopsis}"
            )
            with st.spinner("퀴즈 생성 중..."):
                quiz_json_str = get_chatgpt_response(prompt)

            # JSON 파싱 전, 코드 블록 제거
            quiz_json_str_clean = remove_code_fences(quiz_json_str)

            # JSON 파싱 시도
            try:
                quiz_dict = json.loads(quiz_json_str_clean)
                if "quiz" in quiz_dict:
                    st.session_state.quiz_data = quiz_dict["quiz"]
                    st.success("퀴즈가 생성되었습니다! 아래 문제를 풀어보세요.")
                else:
                    st.error("생성된 JSON에 'quiz' 키가 없습니다. ChatGPT 응답을 확인하세요.")
                    st.write("ChatGPT 응답:")
                    st.code(quiz_json_str_clean)
            except Exception as e:
                st.error("퀴즈 생성에 실패했습니다. ChatGPT가 JSON 형식으로 응답했는지 확인하세요.")
                st.write("에러 메시지:", e)
                st.write("ChatGPT 원본 응답(전처리 후):")
                st.code(quiz_json_str_clean)

    # 2) 퀴즈 풀이
    if "quiz_data" in st.session_state:
        quiz_data = st.session_state.quiz_data
        if "quiz_answers" not in st.session_state:
            st.session_state.quiz_answers = {}

        # 문제 출력
        for idx, item in enumerate(quiz_data):
            st.markdown(f"**문제 {idx+1}:** {item['question']}")
            if f"quiz_q_{idx}" not in st.session_state:
                st.session_state[f"quiz_q_{idx}"] = item["options"][0]  # 기본값
            user_answer = st.radio(
                label=f"문제 {idx+1}의 답변",
                options=item["options"],
                key=f"quiz_q_{idx}"
            )
            # 세션 스테이트에 학생 답안 저장
            st.session_state.quiz_answers[str(idx)] = user_answer

        # 제출 버튼
        if st.button("답안 제출"):
            student_answers = {str(i): st.session_state.quiz_answers[str(i)] for i in range(len(quiz_data))}
            # 채점 요청
            eval_prompt = "다음은 독서 퀴즈 문제와 정답, 그리고 학생의 답변입니다.\n\n"
            for i, item in enumerate(quiz_data):
                eval_prompt += f"문제 {i+1}: {item['question']}\n"
                options_str = ", ".join(item['options'])
                eval_prompt += f"선택지: {options_str}\n"
                eval_prompt += f"정답: {item['correct_answer']}\n"
                eval_prompt += f"학생의 답변: {student_answers[str(i)]}\n\n"
            eval_prompt += (
                "각 문제별로 학생의 답변이 옳은지 그른지 채점하고, "
                "틀린 경우 올바른 해설과 함께 피드백을 제공해줘. "
                "최종 점수와 총평도 함께 작성해줘."
            )

            with st.spinner("채점 및 피드백 중..."):
                quiz_feedback = get_chatgpt_response(eval_prompt)
            st.subheader("채점 및 피드백 결과")
            st.write(quiz_feedback)

    # 페이지 이동 버튼
    if st.button("다음: 독서 토론"):
        st.session_state.current_page = "독서 토론"
        st.rerun()


def page_reading_discussion():
    st.header("💬 독서 토론")

    if st.sidebar.button("독서 토론 페이지 초기화"):
        for key in [
            "debate_started", "debate_round", "debate_chat", "debate_evaluated",
            "debate_topics", "debate_topic", "user_side", "chatbot_side"
        ]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    if "selected_book" not in st.session_state or st.session_state.selected_book is None:
        st.error("선택된 책이 없습니다. 먼저 '책 검색' 페이지에서 책을 선택하세요.")
        return

    selected_book = st.session_state.selected_book
    book_title = remove_html_tags(selected_book.get("title", "제목 없음"))
    st.markdown(f"**책 제목:** {book_title}")

    # 1) 토론 주제 추천
    if st.button("토론 주제 생성"):
        book_synopsis = st.session_state.get("selected_synopsis_final") or remove_html_tags(
            selected_book.get("description", "줄거리 정보가 없습니다.")
        )
        prompt = (
            f"다음 책 '{book_title}'의 줄거리를 바탕으로, 초등학생도 이해할 수 있는 토론 주제 2가지를, "
            "번호나 특수문자 없이 텍스트만으로 각각 한 줄씩 출력해줘.\n\n"
            "토론 주제는 찬성과 반대로 의견이 나눠질 수 있는 주제여야 해."
            "토론 주제는 ~하여야 한다.로 마쳐서 사용자가 찬성하거나 반대를 선택할 수 있어야 해.\n\n"
            f"줄거리:\n{book_synopsis}"
        )
        with st.spinner("토론 주제 생성 중..."):
            discussion_topics_text = get_chatgpt_response(prompt)

        topics = []
        for line in discussion_topics_text.splitlines():
            line = line.strip()
            if line:
                # 앞 번호 제거
                topic = re.sub(r'^[0-9]+[). ]+', '', line)
                topics.append(topic)
        if topics:
            st.session_state.debate_topics = topics
        else:
            st.error("토론 주제 생성에 실패했습니다.")

    if "debate_topics" in st.session_state:
        st.markdown("**추천된 토론 주제:**")
        for topic in st.session_state.debate_topics:
            st.write(f"- {topic}")

    # 2) 토론 시작 전
    if "debate_started" not in st.session_state:
        default_topic = st.session_state.debate_topics[0] if "debate_topics" in st.session_state and st.session_state.debate_topics else ""
        debate_topic_input = st.text_input("토론 주제 입력", value=default_topic)
        user_side = st.radio("당신은 어느 측입니까?", ("찬성", "반대"))
        if st.button("토론 시작"):
            st.session_state.debate_topic = debate_topic_input
            st.session_state.user_side = user_side
            st.session_state.chatbot_side = "반대" if user_side == "찬성" else "찬성"
            st.session_state.debate_started = True
            st.session_state.debate_round = 1
            st.session_state.debate_chat = []
            system_prompt = (
                f"당신은 독서 토론 챗봇입니다. 이번 토론 주제는 '{st.session_state.debate_topic}' 입니다.\n"
                "토론은 다음 순서로 진행됩니다:\n"
                "1. 찬성측 입론\n2. 반대측 입론\n3. 찬성측 반론\n4. 반대측 반론\n"
                "5. 찬성측 최후 변론\n6. 반대측 최후 변론\n"
                f"사용자는 '{st.session_state.user_side}' 측, 당신은 '{st.session_state.chatbot_side}' 측입니다.\n"
                "각 라운드에서는 해당 제목을 명시한 후 의견을 제시해 주세요. "
                "토론 종료 후, 양측의 토론을 평가하여 100점 만점 중 어느 측이 더 설득력 있었는지와 그 이유를 피드백해 주세요."
            )
            st.session_state.debate_chat.append({"role": "system", "content": system_prompt})
            st.rerun()

    # 3) 토론 진행 (채팅 UI 사용)
    if st.session_state.get("debate_started"):
        st.subheader(f"토론 진행: {st.session_state.debate_topic}")

        # 기존 대화 표시 (system 메시지는 표시 안 함)
        for msg in st.session_state.debate_chat:
            if msg["role"] == "system":
                continue  # 시스템 메시지는 숨김
            elif msg["role"] == "assistant":
                st.chat_message("assistant").write(msg["content"])
            else:  # "user"
                st.chat_message("user").write(msg["content"])

        round_titles = {
            1: "찬성측 입론",
            2: "반대측 입론",
            3: "찬성측 반론",
            4: "반대측 반론",
            5: "찬성측 최후 변론",
            6: "반대측 최후 변론"
        }
        current_round = st.session_state.debate_round

        if current_round <= 6:
            st.markdown(f"### 현재 라운드: {round_titles[current_round]}")
            # 사용자 차례?
            if (current_round % 2 == 1 and st.session_state.user_side == "찬성") or \
               (current_round % 2 == 0 and st.session_state.user_side == "반대"):
                placeholder_text = f"{round_titles[current_round]} 메시지를 입력하세요..."
                user_input = st.chat_input(placeholder_text)
                if user_input:
                    st.session_state.debate_chat.append(
                        {"role": "user", "content": f"[{round_titles[current_round]}] {user_input}"}
                    )
                    st.session_state.debate_round += 1
                    st.rerun()
            else:
                # 챗봇 차례
                conversation = st.session_state.debate_chat.copy()
                # 만약 반대측이 첫 라운드(1번)에서 발언해야 하는 경우 특별한 지시
                if current_round == 1 and st.session_state.user_side == "반대":
                    conversation.append({
                        "role": "user",
                        "content": f"[{round_titles[current_round]}] 챗봇은 이번 토론에서 찬성측 입론을 먼저 제시하고, "
                                   "답변 마지막에 '반대측 입론 말해주세요'라고 덧붙여주세요."
                    })
                else:
                    conversation.append({
                        "role": "user",
                        "content": f"[{round_titles[current_round]}]"
                    })

                with st.spinner("챗봇 응답 생성 중..."):
                    bot_response = get_chatgpt_chat_response(conversation)
                st.session_state.debate_chat.append({"role": "assistant", "content": bot_response})
                st.session_state.debate_round += 1
                st.rerun()

        else:
            # 모든 라운드 종료
            if "debate_evaluated" not in st.session_state:
                st.markdown("### 토론 종료 및 평가")
                evaluation_prompt = (
                    "토론이 모두 끝났습니다. 위의 대화 내용을 바탕으로, 찬성측과 반대측 중 어느 측이 더 설득력 있었는지 "
                    "100점 만점으로 평가하고, 그 이유와 함께 구체적인 피드백을 제공해 주세요."
                )
                st.session_state.debate_chat.append({"role": "user", "content": evaluation_prompt})
                with st.spinner("최종 평가 생성 중..."):
                    evaluation_response = get_chatgpt_chat_response(st.session_state.debate_chat)
                st.session_state.debate_chat.append({"role": "assistant", "content": evaluation_response})
                st.session_state.debate_evaluated = True
                st.rerun()
            else:
                st.markdown("### 토론 평가 결과")
                final_evaluation = st.session_state.debate_chat[-1]["content"]
                st.chat_message("assistant").write(final_evaluation)

                # 토론 종료 후 감상문 피드백으로 이동
                if st.button("독서 감상문 피드백으로 이동"):
                    st.session_state.current_page = "독서 감상문 피드백"
                    st.rerun()


def page_reading_feedback():
    st.header("✍️ 독서 감상문 피드백")

    if st.sidebar.button("독서 감상문 피드백 페이지 초기화"):
        st.rerun()

    # 선택된 책 정보 표시
    if st.session_state.get("selected_book"):
        selected_book = st.session_state.selected_book
        book_title = remove_html_tags(selected_book.get("title", "제목 없음"))
        st.markdown(f"**선택된 책:** {book_title}")
    else:
        st.info("현재 선택된 책이 없습니다. 감상문 피드백만 받으려면 감상문을 입력해주세요.")

    st.markdown("### 독서 감상문 입력")
    feedback_input = st.text_area("작성한 독서 감상문", value="", height=200)

    if st.button("피드백 받기"):
        if feedback_input.strip() == "":
            st.error("독서 감상문을 입력해주세요!")
        else:
            book_title = "제목 정보가 없습니다."
            book_synopsis = "줄거리 정보가 없습니다."

            if st.session_state.get("selected_book"):
                selected_book = st.session_state.selected_book
                book_title = remove_html_tags(selected_book.get("title", "제목 없음"))
                book_synopsis = st.session_state.get("selected_synopsis_final") or \
                                remove_html_tags(selected_book.get("description", "줄거리 정보가 없습니다."))

            prompt = (
                "학생이 작성한 독서 감상문에 대해 책의 제목과 줄거리를 바탕으로 긍정적인 피드백과 개선할 점을 구체적으로 설명하고, "
                "개선한 후의 독서 감상문의 예시를 제공해줘.\n\n"
                f"책 제목:\n{book_title}\n\n"
                f"책 줄거리:\n{book_synopsis}\n\n"
                f"감상문:\n{feedback_input}"
            )
            with st.spinner("피드백 생성 중..."):
                feedback = get_chatgpt_response(prompt)
            st.subheader("피드백 결과")
            st.write(feedback)

# === 메인 함수 ===

def main():
    # 세션 상태 기본값 설정
    if "current_page" not in st.session_state:
        st.session_state.current_page = "책 검색"
    if "selected_book" not in st.session_state:
        st.session_state.selected_book = None
    if "selected_synopsis_final" not in st.session_state:
        st.session_state.selected_synopsis_final = None

    # 최신 Streamlit에서 chat 기능 사용 가능
    st.set_page_config(page_title="인공지능 독서 교육 프로그램", page_icon="📚", layout="wide")

    # --- 커스텀 CSS 적용 ---
    st.markdown(
        """
        <style>
        /* 전체 배경 및 컨테이너 스타일 */
        body {
            background-color: #f0f2f6;
        }
        .block-container {
            background-color: #ffffff;
            border-radius: 8px;
            padding: 20px;
        }
        /* 버튼 스타일 */
        .stButton>button {
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 5px;
            padding: 8px 16px;
            margin: 5px;
        }
        /* 사이드바 스타일 */
        .css-1d391kg { 
            background-color: #f8f9fa;
        }
        </style>
        """, unsafe_allow_html=True
    )

    # --- 상단 타이틀 및 안내 ---
    st.title("인공지능 독서 교육 프로그램")
    st.markdown("**학생들과 함께 독서 퀴즈, 독서 토론, 독서 감상문 피드백을 진행해보세요!**")

    # --- 사이드바 메뉴 ---
    pages = ["책 검색", "독서 퀴즈", "독서 토론", "독서 감상문 피드백"]
    if "current_page" not in st.session_state or st.session_state.current_page not in pages:
        st.session_state.current_page = "책 검색"

    current_index = pages.index(st.session_state.current_page)
    menu = st.sidebar.radio("메뉴 선택", pages, index=current_index)
    st.session_state.current_page = menu

    # --- 사이드바 초기화 옵션 ---
    st.sidebar.markdown("---")
    st.sidebar.header("초기화 옵션")
    if st.sidebar.button("전체 초기화"):
        st.session_state.clear()
        st.rerun()

    # --- 페이지별 함수 호출 ---
    if menu == "책 검색":
        page_book_search()
    elif menu == "독서 퀴즈":
        page_reading_quiz()
    elif menu == "독서 토론":
        page_reading_discussion()
    elif menu == "독서 감상문 피드백":
        page_reading_feedback()

if __name__ == '__main__':
    main()
