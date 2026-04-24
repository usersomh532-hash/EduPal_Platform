from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0022_lessoncontent_difficulty_level_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='studentanswer',
            name='selectedoption',
            field=models.CharField(
                db_column='SelectedOption',
                max_length=300,
            ),
        ),
    ]