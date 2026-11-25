# Generated manually for challenge mode targeting.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('challenges', '0004_decode_me_learning_mode_and_mode_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='challenge',
            name='challenge_mode',
            field=models.CharField(
                choices=[('student', 'Student'), ('competitor', 'Competitor'), ('both', 'Both')],
                default='both',
                max_length=16,
            ),
        ),
    ]
