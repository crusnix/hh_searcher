import requests
import streamlit as st
from bs4 import BeautifulSoup
import os
import openai
import json
from dotenv import load_dotenv
import time
from urllib.parse import urlencode, unquote_plus
import re

load_dotenv()

# --- Эти функции можно оставить без изменений ---
def get_access_token():
    token = os.getenv("ACCESS_TOKEN")
    if not token:
        st.error("Токен доступа ACCESS_TOKEN не найден в .env файле.")
    return token

def get_current_user_info():
    access_token = get_access_token()
    if not access_token: return None
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    url = "https://api.hh.ru/me"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

# hh_api_integration_v2.py

@st.cache_data(show_spinner="Загрузка справочника регионов Казахстана...")
def get_area_dictionary():
    """
    Загружает и кэширует справочник регионов ТОЛЬКО для Казахстана.
    Преобразует древовидную структуру в плоский словарь для selectbox.
    """
    try:
        response = requests.get("https://api.hh.ru/areas", timeout=10)
        response.raise_for_status()
        all_countries = response.json()
        
        # 1. Находим объект "Казахстан" в общем списке
        kazakhstan_node = next((country for country in all_countries if country['id'] == '40'), None)

        if not kazakhstan_node:
            st.error("Не удалось найти Казахстан в справочнике регионов HH.ru.")
            return {"Астана": "160", "Алматы": "159"} # Fallback

        area_dict = {}

        def parse_kz_area_node(node):
            """Рекурсивная функция для парсинга регионов внутри Казахстана."""
            # Добавляем в словарь и города, и области
            area_dict[node['name']] = node['id']
            if 'areas' in node and node['areas']:
                for sub_area in node['areas']:
                    parse_kz_area_node(sub_area)

        # 2. Запускаем рекурсивный парсинг только для дочерних регионов Казахстана
        for region in kazakhstan_node['areas']:
            parse_kz_area_node(region)
            
        # 3. Добавляем сам "Казахстан" как опцию для поиска по всей стране
        area_dict[kazakhstan_node['name']] = kazakhstan_node['id']

        # Сортируем словарь по ключам (названиям) для удобства
        return dict(sorted(area_dict.items()))
    
    except requests.exceptions.RequestException as e:
        st.error(f"Не удалось загрузить список регионов: {e}")
        # Возвращаем базовый словарь в случае ошибки
        return {
            "Астана": "160",
            "Алматы": "159",
            "Казахстан": "40"
        }
    
def get_managers(employer_id="24761"):
    access_token = get_access_token()
    if not access_token: return []
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    url = f"https://api.hh.ru/employers/{employer_id}/managers"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('items', [])
    return []

def get_active_vacancies(manager_ids, employer_id="24761"):
    access_token = get_access_token()
    if not access_token: return []
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.3"}
    all_vacancies = []
    for manager_id in manager_ids:
        url = f"https://api.hh.ru/employers/{employer_id}/vacancies/active"
        params = {"page": 0, "per_page": 50, "manager_id": manager_id}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            all_vacancies.extend(response.json().get('items', []))
    return all_vacancies

def get_vacancy_details(vacancy_id):
    url = f"https://api.hh.ru/vacancies/{vacancy_id}"
    headers = {"User-Agent": "ForteTalent/1.3"}
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < 2: time.sleep(2)
            else: st.error(f"Не удалось получить детали вакансии: {e}")
    return None

def clean_vacancy_description(html_description):
    """
    Очищает описание: изолирует русский блок, удаляет шаблоны и форматирует.
    """
    if not html_description: return "", ""
    soup = BeautifulSoup(html_description, 'html.parser')
    text_content = soup.get_text(separator='\n', strip=True)

    # 1. Найти начало русского блока
    russian_start_keywords = ['Обязанности', 'Требования']
    start_pos = -1
    for keyword in russian_start_keywords:
        match = re.search(r'\b' + re.escape(keyword) + r'\b', text_content, re.IGNORECASE)
        if match:
            pos = match.start()
            if start_pos == -1 or pos < start_pos: start_pos = pos
    
    if start_pos != -1: text_content = text_content[start_pos:]

    # 2. Найти конец русского блока (начало казахского дубля)
    kazakh_start_keywords = ['Міндеттері', 'Талаптар']
    end_pos = -1
    for keyword in kazakh_start_keywords:
        match = re.search(r'\b' + re.escape(keyword) + r'\b', text_content, re.IGNORECASE)
        if match:
            pos = match.start()
            if end_pos == -1 or pos < end_pos: end_pos = pos

    if end_pos != -1: text_content = text_content[:end_pos]

    # 3. Удалить рекламные блоки
    pattern_about = re.compile(r"(Что такое ForteBank\?).*?(?=(Обязанности|Требования))", re.DOTALL | re.IGNORECASE)
    pattern_perks = re.compile(r"(Став частью команды Forte).*$", re.DOTALL | re.IGNORECASE)
    cleaned_text = re.sub(pattern_about, '', text_content)
    cleaned_text = re.sub(pattern_perks, '', cleaned_text)
    
    cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text).strip()
    
    # 4. Форматирование
    html_version = cleaned_text
    headers_to_format = ['Обязанности', 'Требования', 'Что мы предлагаем', 'Условия', 'Наш стэк']
    for header in headers_to_format:
        pattern = re.compile(f'({re.escape(header)})\s*:', re.IGNORECASE)
        replacement = f'<br><strong>{header}:</strong>'
        html_version = pattern.sub(replacement, html_version)

    html_version = html_version.replace('\n', '<br>')
    html_version = re.sub(r'(<br>\s*){2,}', '<br>', html_version)
    
    return cleaned_text, html_version

@st.cache_data(show_spinner="Анализ вакансии с помощью AI...")
def generate_keywords_with_openai(vacancy_name, cleaned_vacancy_text):
    """
    Вызывает OpenAI ОДИН РАЗ на вакансию (благодаря кэшу Streamlit),
    чтобы сгенерировать максимально полный набор ключевых слов.
    Принимает только необходимые, неизменяемые части для кэширования.
    """
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        st.error("Ключ OPENAI_API_KEY не найден.")
        return None

    full_text_for_ai = f"Название: {vacancy_name}\n\nОписание:\n{cleaned_vacancy_text}"
    
    system_prompt = """
    Ты — эксперт-рекрутер. Проанализируй вакансию и верни JSON-объект.
    ЗАДАЧА: Максимально полно и точно заполни два поля: must_have и optional, фокусируясь ТОЛЬКО на профессиональных навыках и технологиях.

    ИНСТРУКЦИИ:
    - Используй короткие, атомарные термины (1-2 слова). Например, 'Python', а не 'Опыт работы с Python'.
    - Используй английские термины, только если они есть в вакансии, иначе — использую только русский язык.
    - Не используй синонимы или альтернативные формулировки, только точные термины из вакансии.
    - Не добавляй ничего, что не указано в вакансии.
    - 'must_have': ТОЛЬКО самые критичные, ключевые технологии и навыки. Без них невозможно выполнять работу.
    - 'optional': Вспомогательные, желательные или второстепенные навыки. Полезны, но не обязательны.

    ЗАПРЕЩЕНО:
    - НЕ включай требования к образованию, опыту (годы) или знанию языков.
    - НЕ включай отрасли или альтернативные названия должности.
    - НЕ добавляй описания или пояснения.

    Формат вывода:
    {
    "must_have": [],
    "optional": []
    }

    ВЕРНИ ТОЛЬКО JSON.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Вакансия:\n{full_text_for_ai}"}
            ],
            response_format={"type": "json_object"}, temperature=0.1)
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        st.error(f"Ошибка при обращении к OpenAI API: {e}")
        return None

def advanced_search_resumes_old(structured_keywords, search_filters, mode="Средний"):
    access_token = get_access_token()
    if not access_token: return None
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.5"}

    def format_keyword(kw):
        kw = kw.strip()
        if not kw: return None
        if '/' in kw: return f"({' AND '.join(kw.split('/'))})"
        if ' ' in kw: return f'"{kw}"'
        return kw

    def build_main_query_text(kw, query_mode, user_job_title=None, bank_only=False):
        def format_list(keywords):
            return [f for k in keywords if (f := format_keyword(k))]

        must_have = format_list(kw.get("must_have", []))
        technologies = format_list(kw.get("technologies", []))
        domain = format_list(kw.get("domain", []))

        query_parts = []

        # --- ИЗМЕНЕНИЕ: Сначала добавляем жесткие фильтры от пользователя ---
        if user_job_title:
            query_parts.append(format_keyword(user_job_title))
        if bank_only:
            query_parts.append("банк")

        # --- Затем добавляем гибкую логику по ключевым словам в зависимости от режима ---
        ai_parts = []
        if query_mode == "Строгий":
            if must_have: ai_parts.append(f"({' AND '.join(must_have)})")
            if technologies: ai_parts.append(f"({' OR '.join(technologies)})")
            if domain: ai_parts.append(f"({' OR '.join(domain)})")
        elif query_mode == "Средний":
            if must_have: ai_parts.append(f"({' AND '.join(must_have)})")
            combined_or = technologies + domain
            if combined_or: ai_parts.append(f"({' OR '.join(combined_or)})")
        else:  # Обширный
            all_keywords = must_have + technologies + domain
            if all_keywords: ai_parts.append(f"({' OR '.join(all_keywords)})")

        if ai_parts:
            # Объединяем AI-части в одну группу в скобках, чтобы они не конфликтовали с жесткими фильтрами
            query_parts.append(f"({' AND '.join(ai_parts)})")
        
        
        return " AND ".join(filter(None, query_parts))

    # --- ИЗМЕНЕНИЕ: Извлекаем новые фильтры перед API вызовом ---
    # Мы извлекаем их, чтобы они не попали в `params` напрямую, т.к. они влияют на поле `text`
    user_job_title = search_filters.pop("user_job_title", None)
    bank_only = search_filters.pop("bank_only", False)
    
    # Теперь `search_filters` содержит только "чистые" API-параметры (area, language, etc.)

    strategies = []
    kw = structured_keywords
    main_query_text = build_main_query_text(kw, mode, user_job_title, bank_only)
    
    if main_query_text:
        strategies.append({"name": f"Main Search ({mode})", "params": {"text": main_query_text}, "score": 10})

    found_resumes = {}
    base_url = "https://api.hh.ru/resumes"
    print("\n--- DEBUG: ГЕНЕРАЦИЯ ПОИСКОВЫХ ЗАПРОСОВ ---")
    with st.spinner(f"Выполняю поиск в режиме '{mode}'..."):
        for strategy in strategies:
            # `search_filters` уже не содержит наши кастомные поля
            current_params = {**search_filters, **strategy["params"]}
            query_string = urlencode(current_params, doseq=True)
            human_readable_url = unquote_plus(f"{base_url}?{query_string}")
            print(f"[*] Стратегия '{strategy['name']}':\n    {human_readable_url}\n")
            
            try:
                response = requests.get(base_url, headers=headers, params=current_params, timeout=15)
                response.raise_for_status()
                data = response.json()
                for resume in data.get("items", []):
                    resume_id = resume["id"]
                    if resume_id not in found_resumes:
                        found_resumes[resume_id] = {"data": resume, "score": 0}
                    found_resumes[resume_id]["score"] += strategy["score"]
            except requests.exceptions.RequestException as e:
                st.warning(f"Ошибка при поиске по стратегии '{strategy['name']}': {e}")
    
    if not found_resumes: return {"found": 0, "items": []}
    return {"found": len(found_resumes), "items": sorted(list(found_resumes.values()), key=lambda x: x["score"], reverse=True)}

def advanced_search_resumes(search_params, search_filters):
    """
    Выполняет двухступенчатый поиск: сначала с обязательными и дополнительными
    критериями, а в случае неудачи — только с обязательными.
    """
    access_token = get_access_token()
    if not access_token:
        st.error("Отсутствует токен доступа для поиска.")
        return {"found": 0, "items": []}
    
    headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "ForteTalent/1.6"}
    base_url = "https://api.hh.ru/resumes"

    def format_keyword(kw):
        """Обрабатывает ключевое слово: убирает пробелы, оборачивает фразы в кавычки."""
        kw = kw.strip()
        if not kw: return None
        if '/' in kw: return f"({' AND '.join(kw.split('/'))})"
        if ' ' in kw: return f'"{kw}"'
        return kw

    def build_query_text(must_have_list, should_have_list):
        """Строит текстовую часть запроса."""
        query_parts = []
        
        # Обязательные критерии всегда соединяются через AND
        must_parts = [formatted for kw in must_have_list if (formatted := format_keyword(kw))]
        if must_parts:
            query_parts.append(f"({' AND '.join(must_parts)})")

        # Дополнительные критерии соединяются через OR
        should_parts = [formatted for kw in should_have_list if (formatted := format_keyword(kw))]
        if should_parts:
            query_parts.append(f"({' OR '.join(should_parts)})")
            
        return " AND ".join(query_parts)

    def execute_search(text_query, page_num=0):
        """Выполняет один API-запрос и возвращает результат."""
        if not text_query:
            st.warning("Не заданы обязательные критерии для поиска.")
            return None # Не делаем пустой запрос

        # Добавляем номер страницы в фильтры
        current_filters = {**search_filters, "page": page_num}
        current_params = {**current_filters, "text": text_query}

        query_string = urlencode(current_params, doseq=True)
        human_readable_url = unquote_plus(f"{base_url}?{query_string}")
        print(f"[*] Выполняется запрос:\n    {human_readable_url}\n")
        
        try:
            response = requests.get(base_url, headers=headers, params=current_params, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"Ошибка при поиске: {e}")
            return None

    # --- Шаг 1: "Идеальный" поиск (с дополнительными критериями) ---
    st.info("Этап 1: Поиск по всем заданным критериям...")
    ideal_query = build_query_text(search_params['must_have'], search_params['optional'])
    
    # Получаем номер страницы из фильтров. Если его нет, по умолчанию 0.
    page_number = search_filters.get('page', 0)
    
    results = execute_search(ideal_query, page_number)

    if results is None: # Если произошла ошибка или пустой запрос
        return {"found": 0, "items": []}
    
    # --- Шаг 2: Проверка и "Запасной" (Fallback) поиск ---
    # Мы переходим ко второму этапу ТОЛЬКО если это первая страница и ничего не найдено
    if results.get("found", 0) == 0 and page_number == 0:
        st.warning("По всем критериям кандидаты не найдены. Выполняется поиск только по обязательным...")
        time.sleep(1) # Небольшая пауза для UX
        
        main_query = build_query_text(search_params['must_have'], []) # Дополнительные поля пустые
        fallback_results = execute_search(main_query, page_number)

        if fallback_results:
             if fallback_results.get("found", 0) > 0:
                st.success(f"Найдено {fallback_results.get('found', 0)} кандидатов по обязательным критериям.")
             else:
                st.error("Кандидаты не найдены даже по обязательным критериям.")
             return fallback_results
        else: # Если и второй поиск вернул ошибку
             return {"found": 0, "items": []}
    else:
        # Если найдены результаты на первой или любой другой странице, просто возвращаем их
        st.success(f"Найдено {results.get('found', 0)} кандидатов.")
        # Приводим к единому формату с "score", чтобы не ломать интерфейс
        # (хотя скоринг теперь не используется, это для обратной совместимости)
        items_with_score = [{"data": item, "score": 10} for item in results.get("items", [])]
        results["items"] = items_with_score
        return results