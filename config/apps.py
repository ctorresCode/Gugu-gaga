from django.contrib.staticfiles.apps import StaticFilesConfig


class StaticFilesSinFuentesConfig(StaticFilesConfig):
    # input.css es el fuente de Tailwind (se compila a output.css); no se publica.
    ignore_patterns = StaticFilesConfig.ignore_patterns + ['input.css']
