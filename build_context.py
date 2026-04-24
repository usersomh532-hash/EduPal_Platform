import os

# 1. المجلدات التي سنستبعدها نهائياً (لانها لا تحتوي على كود برمجي يهمه)
EXCLUDE_DIRS = {
    'venv', 'venv310', '.git', '__pycache__', 
    'migrations', 'staticfiles', 'media', '.idea', '.vscode'
}

# 2. الامتدادات التي نريد جمعها (الكود المنطقي والواجهات)
INCLUDE_EXTENSIONS = {'.py', '.html', '.css', '.js'}

# 3. ملفات محددة لا نريدها
EXCLUDE_FILES = {'db.sqlite3', 'build_context.py', 'project_structure.txt'}

output_file = "EduPal_Full_Context.txt"

def collect_project_data():
    with open(output_file, 'w', encoding='utf-8') as outfile:
        outfile.write("PROJECT STRUCTURE OVERVIEW\n")
        outfile.write("="*30 + "\n")
        
        # أولاً: سنضع هيكل الشجرة في بداية الملف ليعرف المجلدات
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            level = root.replace('.', '').count(os.sep)
            indent = ' ' * 4 * (level)
            outfile.write(f"{indent}{os.path.basename(root)}/\n")
            sub_indent = ' ' * 4 * (level + 1)
            for f in files:
                if any(f.endswith(ext) for ext in INCLUDE_EXTENSIONS):
                    outfile.write(f"{sub_indent}{f}\n")

        outfile.write("\n\nFILE CONTENTS\n")
        outfile.write("="*30 + "\n")

        # ثانياً: سنضع محتوى كل ملف
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                if any(file.endswith(ext) for ext in INCLUDE_EXTENSIONS) and file not in EXCLUDE_FILES:
                    file_path = os.path.join(root, file)
                    
                    outfile.write(f"\n\n{'#'*80}\n")
                    outfile.write(f"PATH: {file_path}\n")
                    outfile.write(f"{'#'*80}\n\n")
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
                    except Exception as e:
                        outfile.write(f"Error reading {file_path}: {e}\n")

    print(f"تم بنجاح! الملف جاهز الآن باسم: {output_file}")

if __name__ == "__main__":
    collect_project_data()